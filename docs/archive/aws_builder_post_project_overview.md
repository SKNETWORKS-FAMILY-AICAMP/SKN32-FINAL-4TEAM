# TrueFit: turning "I need a gaming PC under $1,100" into an actual parts list, with a reason for every part

Most shopping tools stop at "here are five products, sorted by relevance." That's not the hard part of buying something you don't already understand. The hard part is turning a vague goal into a full, compatible set, and being able to answer "wait, why this one?" when someone asks. TrueFit is our attempt at that — built so the same engine can eventually plan a purchase in *any* goal-based shopping category, not just one. We proved it out on two domains that don't usually share a codebase, PC building and baby gear, deliberately picked because they have almost nothing in common: one is about compatibility and performance tiers, the other about age-appropriateness and safety.

## How a session actually works

You pick a category, then it's a chat: what it's for, your budget, what matters most to you. No dropdown form — type a full sentence or click a suggested chip, either way it fills the same structured condition set behind the scenes. Once the required fields are in, you get one item per slot (CPU, GPU, RAM, and so on for PC; the equivalent for baby gear), a total against your budget, and a plain-language reason for every single pick. Swap any item, ask "why this GPU" and get an answer grounded in what was actually checked, see review signal rendered honestly instead of smoothed over. Confirm it and the list freezes into a report, with a price-target watch and, for PC builds, a generated assembly guide in real build order.

## The part we actually care about

Underneath is an eight-stage pipeline (intent, requirements, candidates, hard filtering, ranking, verification, budget optimization, explanation), and the rule we didn't bend anywhere in it: **the code decides what's true, the model only writes the sentence describing it.** No part gets picked because an LLM liked it, no compatibility check passes because a model said so. Wherever we do use an LLM — the paragraph explaining a pick, the plain summary of a check — the underlying number or pass/fail was already fixed before the model saw it. If sentence-writing fails, we fall back to a template; the recommendation itself never breaks.

The same discipline shows up in a call we're fairly opinionated about: we never ask a model to judge whether a review is fake. Humans and GPT-4o both land barely above a coin flip at spotting manipulated reviews, so instead of a detector we surface observed signals only — volume, timing bursts, rating deltas against a control group — always labeled as a signal about the product, not a verdict on any single review. Less impressive-sounding than "AI catches fake reviews." That's on purpose.

None of those eight stages know what "GPU" or "onesie" means. What's category-specific — required fields, the question flow, validation rules — lives in a YAML schema per category, not in the pipeline code. PC and baby gear are the two we've wired in; adding a third is meant to be mostly a matter of writing that schema and connecting a catalog, not rebuilding the engine underneath it. That's the actual long-term shape we're building toward: one planning engine, any category.

## Where Strands fits in

Three features run on Strands agents layered over a rule-based version that still works alone: parsing free-text conditions, handling "swap this for something cheaper" by calling the same service functions the API itself uses, and writing the assembly guide off a small RAG-searched document set. All three are opt-in flags, and all three can fail — no key, bad response, timeout — without taking the underlying feature down with them.

## What's still rough

The catalog is synthetic — we say so on-screen rather than pretending otherwise — and review counts for some parts fall back to a placeholder until the full dataset is wired in. Built across four branches in under a week, so there are edges we're still finding. The bet underneath all of it stays the same: a shopping tool is only worth using if it can justify itself, part by part.
