#!/usr/bin/env ruby
# frozen_string_literal: true

require "digest"
require "psych"

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
RUNNER_SHA256 = "8d3a65f662a049eb9b32da4dcb84d22370cd71c960fbe86ca7b31d0a24411151"
WORKFLOW = ".github/workflows/ci-base-trusted.yml"
RUNNER = ".github/scripts/ci-base-trusted.sh"

def reject_ambiguous_yaml(node, path = "document")
  if node.respond_to?(:anchor) && node.anchor
    abort "#{path}: anchors não são permitidos"
  end
  if node.respond_to?(:tag) && node.tag
    abort "#{path}: tags YAML explícitas não são permitidas"
  end

  case node
  when Psych::Nodes::Alias
    abort "#{path}: aliases não são permitidos"
  when Psych::Nodes::Mapping
    keys = {}
    node.children.each_slice(2) do |key, value|
      abort "#{path}: chave não escalar" unless key.is_a?(Psych::Nodes::Scalar)

      reject_ambiguous_yaml(key, "#{path}.<key>")
      identity = key.value
      abort "#{path}: chave duplicada #{identity.inspect}" if keys.key?(identity)

      keys[identity] = true
      reject_ambiguous_yaml(value, "#{path}.#{identity}")
    end
  when Psych::Nodes::Sequence, Psych::Nodes::Stream, Psych::Nodes::Document
    node.children.each_with_index do |child, index|
      reject_ambiguous_yaml(child, "#{path}[#{index}]")
    end
  end
end

workflow_path = ARGV.fetch(0, WORKFLOW)
runner_path = ARGV.fetch(1, RUNNER)
abort "workflow ausente: #{workflow_path}" unless File.file?(workflow_path)
abort "runner ausente: #{runner_path}" unless File.file?(runner_path)

runner_digest = Digest::SHA256.file(runner_path).hexdigest
abort "runner diverge" unless runner_digest == RUNNER_SHA256

source = File.read(workflow_path)
syntax = Psych.parse_stream(source)
abort "workflow deve conter um único documento YAML" unless syntax.children.length == 1

reject_ambiguous_yaml(syntax)
root = syntax.children.first.children.first
abort "top-level deve ser um mapping" unless root.is_a?(Psych::Nodes::Mapping)

source_top_level = root.children.each_slice(2).map(&:first).map(&:value)
expected_top_level = %w[name on permissions jobs]
abort "top-level diverge" unless source_top_level.sort == expected_top_level.sort

document = Psych.safe_load(
  source,
  permitted_classes: [],
  permitted_symbols: [],
  aliases: false,
)
abort "top-level deve ser um mapping" unless document.is_a?(Hash)

# Psych segue YAML 1.1 e resolve a chave plain `on` como true. O GitHub
# preserva `on` como chave textual; normalize somente essa forma canônica.
if document.key?(true)
  abort "top-level contém colisão de on" if document.key?("on")

  document["on"] = document.delete(true)
end

abort "top-level diverge" unless document.keys.sort == expected_top_level.sort
abort "name diverge" unless document["name"] == "CI Base Trusted"

expected_event = { "pull_request_target" => { "branches" => ["main"] } }
abort "evento diverge" unless document["on"] == expected_event
abort "permissions divergem" unless document["permissions"] == { "contents" => "read" }

jobs = document["jobs"]
abort "jobs divergem" unless jobs.is_a?(Hash) && jobs.keys == ["ci-success"]

job = jobs["ci-success"]
expected_job_keys = %w[name runs-on steps]
abort "job ci-success diverge" unless job.is_a?(Hash) && job.keys.sort == expected_job_keys.sort
abort "job ci-success diverge" unless job["name"] == "CI Success"
abort "runner diverge" unless job["runs-on"] == "ubuntu-latest"

expected_steps = [
  {
    "name" => "Checkout da base protegida",
    "uses" => "actions/checkout@#{CHECKOUT_SHA}",
    "with" => {
      "ref" => "${{ github.event.pull_request.base.sha }}",
      "fetch-depth" => 0,
      "persist-credentials" => false,
    },
  },
  {
    "name" => "Validar contrato base-trusted",
    "shell" => "bash",
    "run" => "ruby .github/scripts/check-ci-base-trusted-workflow.rb\n",
  },
  {
    "name" => "Executar mutações base-trusted",
    "shell" => "bash",
    "run" => "python3 .github/scripts/test-ci-base-trusted.py\n",
  },
  {
    "name" => "Validar conteúdo não confiável",
    "shell" => "bash",
    "env" => {
      "PR_NUMBER" => "${{ github.event.pull_request.number }}",
      "BASE_SHA" => "${{ github.event.pull_request.base.sha }}",
      "HEAD_SHA" => "${{ github.event.pull_request.head.sha }}",
    },
    "run" => "bash .github/scripts/ci-base-trusted.sh\n",
  },
]
abort "steps divergem" unless job["steps"] == expected_steps

puts "CI base-trusted workflow contract: ok"
