Prime Agent RLM Kernel and Harness State

Project overview

This project provides the Python side of Prime Agent's recursive language model (RLM) kernel integration. It combines a small JSON-backed harness registry with an asynchronous bridge that lets Python code communicate with the Prime Agent TypeScript host, discover models, spawn recursive child agents, inspect or delete those children, and access persistent harness state.

The included Python components do not implement the TypeScript host itself. They define the kernel-facing protocol, validate host replies, and expose a compact Python API.

Components

Component

Responsibility

harness.py

Persistent local/global records for prompts, memories, skills, subagent specifications, and refinement history

rlm/__init__.py

Async Jupyter communication bridge, model lookup, child-agent lifecycle API, callable module interface, and harness proxy

rlm/mcp_base.py

Base class for authenticated MCP integrations with automatic tool discovery and dynamic async methods

rlm/cli.py

Shared command-line adapter that exposes a skill's run() function through Tyro

TypeScript host

External counterpart that receives typed requests and performs the actual RLM operations

Goals

Preserve useful agent context across calls and process boundaries.

Support session-local and agent-global state.

Provide explicit create, read, update, delete, and upsert operations.

Track changes with timestamps and entry version numbers.

Record refinement attempts and their outcomes.

Recover safely from missing, invalid, or partially incompatible JSON state.

Detect out-of-process file changes before reads and writes.

Send typed asynchronous requests from the Python kernel to the host.

Validate all structured host replies before exposing them to callers.

Return immediately after a child task is admitted, without confusing admission with completion.

Resolve harness storage lazily after a forked kernel receives its session environment.

Let integration packages expose remote MCP tools as ordinary async Python methods.

Reuse host-managed credentials without asking users to copy secrets into kernel code.

Refresh expiring OAuth credentials through the trusted host bridge.

Give every Python skill a consistent, type-driven command-line interface.

Support both synchronous and asynchronous skill entry points.

Technology

Python 3.10 or newer

Jupyter/IPython kernel environment

ipykernel communication support

MCP Python SDK for integration calls

httpx when required by the installed MCP transport signature

tyro for type-driven command-line argument parsing

JSON file persistence

Dataclasses for structured records

pathlib for filesystem paths

UTC ISO 8601 timestamps

The harness module uses only the Python standard library. The RLM bridge expects ipykernel and IPython when running inside a live kernel. Optional MCP re-exports require the project's separate MCP integration module and SDK only when those names are accessed.

System architecture

flowchart TD
    U["Python skill or notebook"] --> API["Callable rlm API"]
    API --> COMM["Jupyter Comm: host.request"]
    COMM --> HOST["Prime Agent TypeScript host"]
    HOST --> CHILD["Child RLM session"]
    API --> MCP["MCP integration"]
    MCP --> SERVER["Remote MCP server"]
    API --> PROXY["Lazy harness proxy"]
    PROXY --> LOCAL["Session harness_state.json"]
    PROXY --> GLOBAL["Global harness_state.json"]

Requests travel over the host.request comm target. The caller awaits the host's admission or management reply. A child agent's eventual answer is delivered through the larger agent messaging/file system, not as the return value of rlm.run().

RLM kernel bridge

Typed response objects

The bridge uses immutable dataclasses for validated host results.

RLMSpawnHandle

Returned when a child task is accepted:

Field

Type

Meaning

rlm_child_id

str

Host-assigned child identifier

name

str

Child name used for follow-up communication

session_dir

Path

Child session workspace

model

str

Model selector used by the child

RLMModel

Describes a model available through active user credentials:

provider

id

name

selector, using the exact provider/model form expected by run()

RLMSubagent

Describes a retained direct child:

rlm_child_id

optional active_session_id

optional session_id

session_name

session_dir

status, restricted to running, completed, or error

Generic host requests

host_request(request_type, payload=None) is the kernel side of the generic host bridge. It:

validates the request type and payload;

confirms Jupyter comm support is available;

installs comm handlers on the kernel control channel when possible;

opens a comm on host.request;

sends the payload with the trusted request type applied last;

resolves an asyncio future for status: ok;

raises RuntimeError for host errors or unexpected statuses;

closes the comm after a terminal reply.

Applying the trusted request type last prevents a caller-supplied type key from rerouting the request.

Child-agent lifecycle API

Spawn a child

import rlm

handle = await rlm(
    "Inspect the parser and report the likely cause of the failing test.",
    model="provider/model-id",
)

print(handle.rlm_child_id)
print(handle.name)
print(handle.session_dir)

run(prompt, **kwargs) sends an rlm.run request. The prompt must be a string. Keyword arguments are passed to the host inside the request's kwargs object.

The returned RLMSpawnHandle confirms admission only. It is not the child's final answer.

Discover models

models = await rlm.find_models(query="reasoning", limit=8)

for model in models:
    print(model.selector, model.name)

find_models() calls rlm.find_models and validates every model entry.

List direct children

children = await rlm.list_subagents()

for child in children:
    print(child.session_name, child.status)

Only children retained by the current parent session are returned.

Delete a child

deleted = await rlm.delete_subagent(children[0])

# A child ID or other host-supported string selector can also be used.
deleted = await rlm.delete_subagent("child-id")

The target must be a non-empty string or an RLMSubagent. The host returns the deleted child record, which is validated before being returned.

Callable interfaces

The bridge supports several equivalent styles:

import rlm

handle_a = await rlm("Do the subtask")
handle_b = await rlm.run("Do the subtask")
handle_c = await rlm.rlm("Do the subtask")
handle_d = await rlm.rlm.run("Do the subtask")

This works because both the exported rlm object and the imported module are asynchronous callables.

Lazy harness proxy

rlm.harness is a proxy rather than a state object resolved at import time. Prime Agent may pre-import the module in a forkserver before session-specific environment variables exist. Resolving on every access ensures each forked kernel sees its own session configuration.

Proxy behavior is deliberately defensive:

a configured session resolves to its persistent local store;

a genuinely unconfigured local session receives an empty in-memory view, while local mutations raise an explanatory error;

global_=True remains available for persistent global operations;

unexpected resolution failures fall back to a shared in-memory state so namespace access does not crash the kernel;

resolution is retried on later accesses, allowing persistence to begin once the environment becomes valid.

Optional MCP exports

McpIntegration, McpToolError, and NotEnabled are declared public but imported lazily from mcp_base. A normal import rlm therefore does not require the optional MCP SDK. Accessing one of these names triggers the integration import.

MCP integration framework

McpIntegration is the base class for Python skill packages backed by Model Context Protocol servers. A subclass declares its server identity and endpoint, then inherits authentication, connection setup, tool discovery, invocation, and result parsing.

Minimal integration

from rlm import McpIntegration


class LinearIntegration(McpIntegration):
    server = "linear"
    url = "https://example.com/mcp"


linear = LinearIntegration()

After the first tool discovery, server tools behave like normal asynchronous methods:

issues = await linear.list_issues(team="Engineering")
tools = await linear.list_tools()

# Explicit form for wrappers or dynamically selected tool names.
issue = await linear.call_tool("get_issue", {"id": "ENG-123"})

Subclasses must set a non-empty server. They may set url, configure bearer_token_env, or override _open_session() for non-HTTP transports such as stdio.

Credential resolution

The integration uses the same Prime Agent directory resolution as the harness:

PRIME_AGENT_CODING_AGENT_DIR;

PI_CODING_AGENT_DIR;

~/.prime/agent.

Credentials are read from <agent-dir>/auth.json using the provider key mcp:<server>. The module deliberately treats missing, unreadable, malformed, or non-object authentication data as unavailable.

Credential priority is:

a non-empty static token from the subclass's bearer_token_env;

an api_key credential from auth.json;

a fresh OAuth access token from auth.json;

a host-side OAuth refresh request.

API-key values support literal text and environment-variable indirection. Values beginning with ! are ignored in the kernel because command indirection must be resolved and injected by the trusted host.

OAuth tokens are treated as expired 30 seconds early to reduce the chance of expiration during a request. If stored credentials exist but the token is stale, _resolve_token() asks the host to process mcp.refresh, then re-reads and revalidates auth.json. It never trusts token data returned directly by the refresh request.

If no usable credentials exist, NotEnabled explains that the integration must be connected through Prime Agent's /mcp login <server> command. A refresh failure is reported separately as a recoverable runtime failure instead of being mislabeled as a missing login.

Host-resolved configuration

Before connecting, _resolve_config() requests mcp.config from the host. A valid host response may override:

the MCP server URL;

additional HTTP headers.

If the host request fails or contains no usable URL, the class-level url is used. Configured headers are normalized to strings. The generated Authorization: Bearer ... header is applied last so configuration cannot override the resolved credential.

Transport compatibility

MCP SDK releases expose streamable HTTP under different callable names and signatures. The framework:

searches for streamablehttp_client and then streamable_http_client;

uses the transport's headers parameter when supported;

otherwise creates an httpx.AsyncClient when the transport expects http_client;

raises an explicit error for unsupported signatures;

opens the transport and ClientSession through an AsyncExitStack;

initializes the MCP session before use.

Imports are lazy so installing or importing an integration package does not fail merely because the MCP SDK is absent. The SDK is required when an actual MCP connection is opened.

Tool discovery and dynamic methods

Tools are discovered on first use and cached as dictionaries containing:

name;

description;

inputSchema.

An asyncio.Lock prevents simultaneous first-use calls from performing duplicate discovery. list_tools() returns copies of the cached records.

Unknown public attributes become async call wrappers through __getattr__(). Before invocation, the wrapper confirms that the requested name exists in the discovered tool registry. If it does not, the resulting AttributeError lists the available tools. Private names beginning with _ are never converted into tool calls.

Tool schemas and descriptions are attached to dynamic wrapper documentation when discovery has already populated the cache.

Per-call sessions

Tool metadata is cached, but live MCP sessions are not. call_tool() opens and closes a fresh initialized session for every invocation. This adds connection latency but avoids retaining sessions across kernel snapshot/restore, idle disconnects, or token rotation.

Result normalization

_parse_result() converts MCP SDK results into useful Python values using this priority:

if isError is true, raise McpToolError with collected text;

return structuredContent when it is not None, including valid empty dictionaries and lists;

join text content blocks with newlines;

convert non-text blocks with model_dump(mode="json") when supported;

return the original result when no recognized content exists.

This prevents server-declared errors from looking like successful tool output and prefers structured data without discarding falsy-but-valid values.

Shared skill CLI

The CLI helper converts a Python skill function into a console command with minimal per-skill boilerplate. Tyro inspects the function signature and type annotations, parses command-line arguments, invokes the function, awaits asynchronous results when necessary, and prints any non-None return value.

Normalized source

The pasted formatting artifacts normalize to the following Python:

"""Shared CLI helpers for Prime Agent Python skills."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any, Callable

import tyro


async def run_cli(func: Callable[..., Any], prog: str | None = None) -> None:
    """Parse CLI arguments for a skill function and print a non-None result."""
    result = tyro.cli(func, prog=prog)
    if inspect.isawaitable(result):
        result = await result
    if result is not None:
        print(result)


def cli() -> None:
    """Run `<skill>.run` for a console script named exactly after the skill import."""
    prog = Path(sys.argv[0]).stem
    try:
        module = __import__(prog)
    except ImportError as exc:
        raise RuntimeError(
            f"Could not import Python skill module {prog!r}. "
            "The console-script name must match the skill import name exactly; "
            "use underscores instead of dashes."
        ) from exc
    run = getattr(module, "run", None)
    if not callable(run):
        raise RuntimeError(f"{prog} does not expose a callable run()")
    asyncio.run(run_cli(run, prog=prog))

run_cli() behavior

run_cli(func, prog=None) is the reusable asynchronous adapter:

pass the supplied function to tyro.cli();

let Tyro build and parse the CLI from its signature and annotations;

inspect the returned value;

await it when it is awaitable;

print it only when it is not None.

This supports both forms without separate wrappers:

def run(name: str, count: int = 1) -> str:
    return " ".join([f"Hello, {name}!"] * count)

async def run(query: str, limit: int = 5) -> list[str]:
    return await search_documents(query=query, limit=limit)

inspect.isawaitable() is broader than checking only coroutine functions. It correctly handles functions that are synchronous when called but return a custom awaitable.

cli() discovery convention

The console-script executable name determines which skill module is imported:

console command name -> Python module name -> module.run()

For example, a console command named document_search imports document_search and invokes its callable run attribute. Dashes are intentionally unsupported because document-search is not a valid import name under this convention; use underscores instead.

The helper raises a clear RuntimeError when:

the command-named module cannot be imported; or

the imported module does not expose a callable run().

Finally, asyncio.run() owns the event loop for the console process and executes the shared asynchronous adapter.

Packaging example

[project]
dependencies = [
  "tyro",
]

[project.scripts]
document_search = "rlm.cli:cli"

The command name must match the importable skill module exactly:

src/
├── document_search.py
└── rlm/
    └── cli.py

Output contract

A None result produces no standard output.

Strings are printed directly.

Lists, dictionaries, dataclasses, and other objects use Python's normal print() representation.

Exceptions from Tyro, the skill function, or awaited work propagate to the console process.

For machine-to-machine usage, individual skills should return a deliberately serialized format such as JSON rather than relying on arbitrary object representations.

Core data model

HarnessEntry

Each reusable harness record contains:

Field

Type

Purpose

id

str

Stable identifier, generated from the title when omitted

kind

prompt, memory, skill, or subagent

Entry category

title

str

Human-readable name

content

str

Instructions, notes, memory, or specification text

path

str

Logical grouping such as general or policy

scope

local or global

Persistence scope

reference

dict

Executable reference metadata, primarily for Python skills

arguments

dict

Skill argument contract or other structured inputs

metadata

dict

Extensible application metadata

source

str

Origin of the entry; defaults to agent

created_at

str

UTC creation timestamp

updated_at

str

UTC last-update timestamp

version

int

Starts at 1 and increments on update

RefinementEvent

A refinement event records:

a stable event ID;

the trigger or observed problem;

one or more changes made;

optional evidence;

optional outcome;

a UTC creation timestamp.

Persistence and scope

State is stored in a file named harness_state.json.

Local state path resolution

Local state uses the first available location:

an explicit state_dir passed to get_harness_state();

RLM_HARNESS_STATE_DIR;

<RLM_SESSION_DIR>/harness.

If no local location is available, the module raises RuntimeError. This is intentional so local writes do not silently fall back to global state.

Global state path resolution

Global state uses the first available location:

an explicit state_dir passed with global_=True;

RLM_GLOBAL_HARNESS_STATE_DIR;

<agent-dir>/harness.

The agent directory uses PRIME_AGENT_CODING_AGENT_DIR, then PI_CODING_AGENT_DIR, and finally ~/.prime/agent.

Entry IDs displayed by overview() can be passed back in scoped form, such as local:deployment_notes or global:python_search. A global: prefix routes the operation to the global store.

Public API

State access

get_harness_state(state_dir=None, global_=False) returns a cached HarnessState for a resolved path and scope.

HarnessState.load() reloads state from disk.

HarnessState.save() serializes the complete state as formatted JSON.

HarnessState.snapshot() returns a dictionary representation.

HarnessState.overview() produces a concise, human-readable inventory.

Generic entry operations

create(kind, title, content, ...) creates a new entry and fails if its ID exists.

get(kind, id, ...) returns an entry or None.

list(kind=None, ...) returns sorted entries, optionally filtered by kind.

update(kind, id, title, content, ...) updates an existing entry and fails if it is missing.

upsert(kind, title, content, ...) creates or replaces an entry.

delete(kind, id, ...) deletes an entry and returns whether it existed.

Valid kinds are prompt, memory, skill, and subagent.

When optional path, reference, arguments, or metadata values are omitted during an update, their existing values are preserved. Passing an explicit empty dictionary clears the matching dictionary field.

Convenience operations

The class supplies category-specific helpers:

create_memory, update_memory, delete_memory

create_prompt_note, update_prompt_note, delete_prompt_note

create_skill, update_skill, delete_skill

create_subagent, update_subagent, delete_subagent

Refinement operations

plan_refinement() creates a short diagnostic and validation checklist.

record_refinement() persists the trigger, changes, evidence, and outcome.

Python skill contract

A skill entry must provide a reference dictionary with:

type set to python;

either import or python_import as a non-empty string;

either callable or call_pattern as a non-empty string.

Example:

skill_reference = {
    "type": "python",
    "import": "prime_tools.search:search_documents",
    "callable": "search_documents",
}

create_skill() always validates this contract. update_skill() validates it only when a replacement reference is supplied.

Quick start

import os
from pathlib import Path

from rlm import get_harness_state

session_dir = Path("./runtime/session-001").resolve()
os.environ["RLM_SESSION_DIR"] = str(session_dir)

state = get_harness_state()

memory = state.create_memory(
    title="Preferred response style",
    content="Lead with the result and keep setup instructions concise.",
    path="preferences",
)

state.update_memory(
    memory.id,
    title=memory.title,
    content="Lead with the result, then provide concise setup and verification steps.",
)

state.record_refinement(
    trigger="Setup instructions were too long",
    changes=["Shortened the setup section", "Added one verification command"],
    evidence="User requested a more direct answer.",
    outcome="Pending validation on the next response.",
)

print(state.overview())

Skill registration example

state.create_skill(
    title="Document search",
    content="Search indexed documents and return the best matching passages.",
    path="retrieval",
    reference={
        "type": "python",
        "import": "prime_tools.search:search_documents",
        "callable": "search_documents",
    },
    arguments={
        "query": {"type": "string", "required": True},
        "limit": {"type": "integer", "default": 5},
    },
)

Global state example

global_state = get_harness_state(global_=True)

global_state.create_prompt_note(
    title="Safety review",
    content="Review destructive operations before execution.",
    global_=True,
)

# A scoped ID from overview() can also route a later operation.
entry = global_state.get("prompt", "global:safety_review")

JSON structure

The persisted document uses schema version 1:

{
  "schema": 1,
  "entries": {
    "prompt": {},
    "memory": {},
    "skill": {},
    "subagent": {}
  },
  "refinements": []
}

On load, unknown entry fields are ignored. Invalid entry collections and malformed records are skipped. An unreadable file, invalid JSON, or a valid JSON value that is not an object is treated as empty state; the next save rewrites it.

Behavioral details

Generated IDs lowercase titles, replace non-alphanumeric runs with underscores, remove empty segments, and truncate the result to 80 characters.

If title normalization produces no ID, the entry kind is used as the fallback.

Lists are sorted by kind, path, title, and ID.

Updates preserve created_at, refresh updated_at, and increment version.

The in-process cache is keyed by resolved state-file path and scope.

Before normal reads and mutations, file modification time is compared with the last loaded value. A detected external change triggers a reload and reduces the chance of overwriting a newer host-side edit.

Testing strategy

Recommended automated tests should cover:

local and global path resolution;

missing local environment configuration;

ID normalization and 80-character truncation;

create, duplicate-create, update, upsert, get, list, and delete behavior;

preservation and explicit clearing of optional dictionaries;

Python skill-reference validation;

version and timestamp changes;

scoped local: and global: identifiers;

malformed and partially incompatible JSON input;

external file modification followed by cache synchronization;

snapshot and overview output;

refinement planning and recording.

successful, error, and unexpected-status host replies;

control-channel comm-handler installation with missing and complete kernels;

payload validation for every public async function;

malformed spawn handles, model records, and subagent records;

all supported subagent statuses and optional session IDs;

lazy harness resolution before and after session environment setup;

unconfigured-local and unexpected-error fallback behavior;

callable module, callable object, and explicit method forms;

lazy MCP imports without requiring the MCP SDK during ordinary imports;

comm closure and future resolution across kernel threads.

missing, malformed, API-key, fresh OAuth, and expired OAuth credentials;

environment-token priority and command-indirection rejection;

successful and failed host-side token refresh;

host configuration override and class-URL fallback;

both supported streamable-HTTP transport names and signatures;

authorization-header precedence over configured headers;

concurrency-safe, single-pass tool discovery;

dynamic tool methods, missing tool errors, and private attributes;

fresh session creation and cleanup for each MCP tool call;

structured, text, non-text, empty, and server-error result parsing.

synchronous, coroutine, and custom-awaitable skill results;

suppression of None and printing of non-None results;

console-name-to-module import resolution;

missing modules and modules without callable run() functions;

Tyro parsing for required, optional, and typed skill parameters;

underscore command names and rejection guidance for dashed names.

Run a basic syntax check with:

python -m py_compile rlm/harness.py
python -m py_compile rlm/__init__.py
python -m py_compile rlm/mcp_base.py
python -m py_compile rlm/cli.py

Known limitations

Persistence rewrites the entire JSON file for every mutation.

Writes are not atomic; an interruption during serialization could leave a partial file.

Modification-time synchronization is not a file lock. Simultaneous writers can still race between reload and save.

Refinement IDs are based on the current event count, so deletion or manual file editing could create collisions.

The loader reads the schema value but does not yet perform schema migrations.

Corrupt or unreadable state is treated as empty rather than backed up or surfaced as an error.

in_memory=True is supported internally by HarnessState, but it is not exposed through get_harness_state().

The module stores skill and subagent specifications but does not validate or execute subagent behavior.

host_request() has no built-in timeout or cancellation cleanup, so a silent host can leave a caller awaiting indefinitely.

The comm closes after a recognized terminal reply, but opening or sending failures are not wrapped with explicit comm cleanup.

Runtime behavior depends on private or version-sensitive Jupyter kernel attributes such as control_handlers and comm_manager.

find_models() verifies that limit is an integer but does not enforce a positive range locally.

run() accepts an empty prompt because it validates type but not content.

The callable-module technique mutates the module object's class, which is powerful but unconventional for type checkers and some tooling.

The degraded in-memory harness favors kernel availability over visibility of unexpected persistence errors.

Authentication file reads are synchronous and occur inside async workflows.

auth.json is read without an explicit encoding and without coordination with concurrent host writes.

Host configuration errors silently fall back to class defaults, which favors availability but can hide a configuration problem.

Tool discovery is cached for the integration object's lifetime, so server-side tool changes are not detected automatically.

Dynamic wrappers primarily accept keyword arguments; positional tool arguments are not supported.

A fresh MCP connection per tool call increases latency and authentication traffic.

Result parsing joins all text blocks and does not retain their original annotations or content-block boundaries.

Images and embedded resources are normalized generically rather than exposed through dedicated typed result classes.

Console scripts cannot use dashed names when module discovery depends directly on the executable stem.

asyncio.run() cannot be called from a thread that already has a running event loop, though ordinary console entry points do not normally have one.

The dynamically imported module name is derived from sys.argv[0], so renamed or wrapped executables can break discovery.

__import__() returns the top-level package for dotted names, making this convention best suited to single-segment skill modules.

Arbitrary non-string results are printed with Python representations rather than a stable serialization format.

Import-time errors raised inside a skill can be reported as an inability to import the skill, reducing diagnostic precision.

Recommended next improvements

Write to a temporary file and atomically replace the state file.

Add cross-process locking around the reload-modify-save transaction.

Back up malformed state before replacing it.

Add explicit schema migration functions.

Add a public in-memory factory for tests and ephemeral sessions.

Introduce typed structures for skill references and argument contracts.

Add a configurable retention limit for refinement history.

Package the module with unit tests and a small command-line inspector.

Add configurable host-request timeouts and cancellation-safe comm cleanup.

Define a versioned request/reply protocol shared with the TypeScript host.

Add structured error codes instead of reducing host failures to message strings.

Validate prompt content and model-search limits before sending requests.

Publish type stubs or a typed protocol for the callable-module interface.

Add integration tests across supported IPython and ipykernel versions.

Read credentials asynchronously or cache them with safe invalidation.

Add atomic host writes and retry-aware reads for auth.json.

Make configuration fallback observable through structured diagnostics.

Add an explicit refresh_tools() method or tool-cache time-to-live.

Generate typed wrappers from each tool's JSON Schema.

Add configurable connection pooling for environments without kernel snapshots.

Preserve multimodal MCP content through documented typed result objects.

Declare and continuously test the supported MCP SDK compatibility range.

Permit an explicit module or callable override instead of relying only on the executable name.

Support dashed console names through a declared command-to-module mapping.

Distinguish a missing skill module from an ImportError raised inside that module.

Add an optional JSON output mode for stable automation output.

Publish a protocol for valid skill run() signatures and return values.

Add a synchronous adapter for callers that already own an event loop.

Suggested project layout

prime-agent-harness/
├── pyproject.toml
├── README.md
├── src/
│   └── rlm/
│       ├── __init__.py
│       ├── cli.py
│       ├── harness.py
│       └── mcp_base.py
└── tests/
    ├── test_harness_crud.py
    ├── test_paths_and_scopes.py
    ├── test_serialization.py
    ├── test_skill_validation.py
    ├── test_host_request.py
    ├── test_rlm_lifecycle.py
    ├── test_harness_proxy.py
    ├── test_mcp_auth.py
    ├── test_mcp_transport.py
    ├── test_mcp_tools.py
    ├── test_mcp_results.py
    └── test_cli.py

Definition of done

The project is production-ready when:

its public API and environment variables are documented;

unit tests cover all CRUD, scope, persistence, and recovery paths;

writes are atomic and guarded against concurrent modification;

invalid-state recovery preserves diagnostic evidence;

schema upgrades are explicit and tested;

packaging declares the supported Python versions;

integration tests confirm compatibility with the Prime Agent TypeScript host and RLM bridge;

the host-request protocol has explicit timeout, cancellation, and error semantics;

model discovery and child-agent lifecycle operations validate both requests and replies;

callable import styles are documented and covered by type-aware tests;

supported IPython and ipykernel versions are declared and tested;

credentials are refreshed without exposing interactive login or secrets to the kernel;

supported MCP SDK transport variants are tested;

dynamic tools provide predictable discovery, validation, and error behavior;

structured and multimodal results have stable normalization rules;

synchronous and asynchronous skills share one documented console contract;

console-script names, import names, and packaging metadata remain aligned;

CLI output is predictable for both human use and automation.
