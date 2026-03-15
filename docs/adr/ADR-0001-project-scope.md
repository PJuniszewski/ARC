# ADR-0001: Initial Project Scope

## Status
Accepted

## Context
ARC could easily balloon into a generic agent platform, memory framework, or policy runtime.
That would kill focus.

## Decision
The project will initially focus on:

- portable archive format
- builder/loader model
- semantic context packaging
- trust and provenance basics

It will not initially focus on:

- full agent runtime
- universal plugin ecosystem
- advanced semantic merge across all domains

## Consequences
The repo stays sharper and implementation can start sooner.

