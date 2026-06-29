# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**Aurora** is at the idea stage. The repository currently contains only `INIT.md` — a vision document, not code. There is no build system, no tests, no source tree, and no git history yet. Architectural decisions (framework, structure, stack) are still open and should be made *with* the user, not assumed.

When the user asks to "start building," expect to scaffold from scratch and to make foundational technology choices collaboratively.

## What Aurora is meant to be

A personal AI assistant for the user (a first-time PA "client") to declutter their digital life. Intended capabilities, per `INIT.md`:

- Access to **email** and **calendars**; never let the user miss deadlines, tasks, meetings, or email replies.
- General **chat**, **research**, **finance management**, and **note-taking via Obsidian**.
- **Multimodal** input: text, PDFs, images, and ideally voice.
- A strong emphasis on a system that **learns and self-reflects** — adjusting its practices over time — rather than "just another AI agent." The user explicitly wants structure and self-improvement, and is unsure of their own preferences, so part of the work is helping surface and codify those.

## Stated preferences and constraints

These come from the user directly and should steer technical choices:

- **LLM API:** DeepSeek is preferred (cited as very cheap). Default to it unless there's a clear reason to do otherwise.
- **Frameworks:** Open to agentic platforms (e.g., Hermes) and **n8n**. Priority is on solutions where agents can **learn and adjust over time**.
- The user wants to be guided on personal-assistant best practices and on how to make the agent self-learn/self-reflect — treat these as design problems to solve, not givens.

## Deployment target (VPS)

The user has a VPS for hosting Aurora:

- Connect with `ssh prod`.
- Work under `/home/mahdi`.
- Privileged operations require `sudo`.

Treat the VPS as a real production-adjacent environment: confirm before destructive or outward-facing actions there.
