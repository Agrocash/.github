#!/usr/bin/env ruby
# frozen_string_literal: true

require "psych"

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
WORKFLOW = ".github/workflows/ci.yml"

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

path = ARGV.fetch(0, WORKFLOW)
abort "workflow ausente: #{path}" unless File.file?(path)

source = File.read(path)
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

# Psych segue YAML 1.1 e resolve a chave plain `on` como true. O workflow do
# GitHub preserva `on` como chave textual; normalize somente essa forma canônica.
if document.key?(true)
  abort "top-level contém colisão de on" if document.key?("on")

  document["on"] = document.delete(true)
end

abort "top-level diverge" unless document.keys.sort == expected_top_level.sort
abort "name diverge" unless document["name"] == "CI"

expected_event = { "pull_request" => { "branches" => ["main"] } }
abort "evento diverge" unless document["on"] == expected_event
abort "permissions divergem" unless document["permissions"] == { "contents" => "read" }

jobs = document["jobs"]
abort "jobs divergem" unless jobs.is_a?(Hash) && jobs.keys == ["ci-success"]

job = jobs["ci-success"]
abort "job ci-success diverge" unless job.is_a?(Hash) && job.keys.sort == %w[name runs-on steps].sort
abort "job ci-success diverge" unless job["name"] == "CI Success"
abort "runner diverge" unless job["runs-on"] == "ubuntu-latest"

expected_steps = [
  {
    "name" => "Checkout",
    "uses" => "actions/checkout@#{CHECKOUT_SHA}",
    "with" => { "fetch-depth" => 0, "persist-credentials" => false },
  },
  {
    "name" => "Validar contrato do workflow",
    "shell" => "bash",
    "run" => "ruby .github/scripts/check-ci-workflow.rb\n",
  },
  {
    "name" => "Executar mutações do workflow",
    "shell" => "bash",
    "run" => "python3 .github/scripts/test-ci-workflow.py\n",
  },
  {
    "name" => "Validar diff e profile",
    "shell" => "bash",
    "run" => <<~SHELL,
      set -euo pipefail
      git diff --check "${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }}"
      test -s profile/README.md
    SHELL
  },
]
abort "steps divergem" unless job["steps"] == expected_steps

puts "CI workflow contract: ok"
