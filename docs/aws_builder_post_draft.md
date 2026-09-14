# What actually breaks when you add Strands agents to a rule engine that already works

We're building TrueFit for the Agents for Humans hackathon, which requires using the Strands Agents SDK somewhere in the submission. Going in, I assumed the hard part would be prompting. It wasn't. The hard part was deciding, function by function, where an agent was even allowed to touch our data, and then handling the day it inevitably said something wrong.

TrueFit is a shopping planner meant to eventually cover any goal-based purchase, not just one category. Right now it runs on two pretty different domains: building a PC and buying baby gear, picked on purpose because they share almost nothing except the end shape — a recommended parts list with a total price and a stated reason for every pick. Getting there differs enough between the two that we built a rule-based conversation engine first and only added agents afterward, one at a time, behind feature flags.

That ordering mattered more than I expected going in.

## The rule engine came first, on purpose

Before any agent existed, condition-gathering (what do you want it for, what's your budget, what matters most) ran entirely on keyword matching against a YAML schema per category. No LLM at all. That wasn't a stopgap we meant to replace — it's still the fallback path today. Every one of our three Strands agents sits on top of a working rule-based system and can fail back into it without the user ever noticing.

All three agent modules ended up with the same shape for `available()`:

```python
def available() -> bool:
    return (not MOCK_MODE and CONDITIONS_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))
```

If that's False (no key, a test run, or the flag is just off) the request goes down the rule path instead, and the caller never has to know which one ran. If I were telling someone starting a hackathon project with a required SDK what to do first, it'd be this: get the deterministic version working, then add the agent as a layer you can switch off. Not only because it's safer, but because it gives you something to diff against once the agent starts doing something you didn't expect.

## Three agents, three jobs

- `conditions_agent` reads a free-text message during the condition chat and calls tools to fill in slots (budget, priority, purpose) instead of the keyword matcher.
- `result_agent` handles requests like "swap the GPU for something cheaper" or "why did you pick this one" after a recommendation exists, by calling the *same service functions the REST API itself uses* (`list_alternatives`, `swap_item`, `patch_item`) as tools.
- `assembly_guide_agent` takes the confirmed parts list and writes step-by-step build instructions, citing a small RAG-searched document set for anything part-specific.

None of them are allowed to make a judgment call that the rest of the system doesn't already make. That constraint predates the agents — the verification and explanation stages of our recommendation pipeline were scoped early on as "the code decides pass or fail, the model only writes the sentence," and when we added agents we kept the same split. The assembly guide agent's system prompt spells it out directly:

```
각 단계마다 search_guide 도구로 그 부품에 확인할 점이 있는지 찾아보고, 찾은 내용을
그대로 반영해 1~2문장으로 안내합니다. 검색 결과가 없거나 그 부품과 관련 없으면
"특별히 확인할 점은 없습니다"라고 정직하게 씁니다 — 없는 내용을 지어내지 않습니다.
```

("For each step, check whether the search_guide tool finds anything worth flagging for that part, and write it faithfully. If nothing relevant comes back, say so honestly — don't invent a caution that isn't there.")

The build order itself (case, PSU, motherboard, CPU, cooler, RAM, storage, GPU) also isn't something the model gets to decide. It's a hardcoded list. Assembly order is a convention, not an opinion, so there's no reason to let an LLM reinvent it on every call and every reason not to.

The RAG side of that agent is intentionally small: 18 short hand-written documents, embedded once and cached in process, searched with plain cosine similarity. No vector database. At that document count a vector store would have been pure overhead, and it's the same reasoning our verification stage already used for its own evidence lookup, so the assembly guide agent just reuses that module as a tool instead of inventing a second retrieval path.

## Where it actually broke

The condition agent's job sounds simple: pull a budget and a priority out of a sentence. But money parsing surfaced the one bug I'd actually call interesting. We support Korean amounts ("150만원"), dollar amounts, and bare numbers, and the model's own behavior turned out to be part of the problem. Given "1,500,000 won," gpt-4o-mini would often split that into two separate tool calls instead of one: `set_condition("budget_max", "1500000")` followed immediately by `set_condition("currency", "KRW")`. Taken literally, the first call alone is ambiguous — a bare "1500000" from a user we'd already tagged as dollar-preferring would get read as $1,500,000 and land at an eye-watering KRW figure.

The fix lives in the tool's backing dataclass: when a currency call arrives right after a bare number was cached from the previous call, we re-interpret the cached number using the currency that just arrived, instead of trusting the first call's guess in isolation.

```python
elif key == "currency" and self._bare_budget is not None and str(raw).strip().upper() in ("KRW", "USD"):
    # the model splits "1,500,000 won" into two calls (observed repeatedly) — reinterpret
    # the bare number now that currency has arrived, or 1,500,000 reads as USD
```

It's a patch for one model's specific habit, and I'm not fully happy with it, but it's a good illustration of the gap between "the SDK makes tool calling easy" and "the tool calls you actually get back match what you designed for." You still have to sit and read what comes back.

The other bug was more structural. Early on, the system prompt baked in "here's the next question to ask," computed once at the start of the turn. After the agent called a tool that filled exactly that field, the tool's own return string *also* carried a freshly recomputed next question, and the model, holding both versions, sometimes asked the same question twice in one reply. We only caught it by reading transcripts, not because anything failed loudly. The fix was to stop putting the next question in the system prompt at all, and only ever surface it inside a tool's return value, so there's one source of truth per turn instead of two that can drift apart mid-conversation.

## The fallback isn't an afterthought

Every agent here has a non-agent escape hatch, and none of them fail silently in the bad sense. The assembly guide agent catches any exception from the Strands call and drops straight into a rule-based fallback that still runs the exact same RAG search, just writes the sentence from a template instead of an LLM. The user gets a slightly flatter guide, never an error screen. The condition and result agents fall back to their respective rule engines the same way.

This is probably the least flashy part of the whole SDK integration, and it's the part I'd defend hardest if someone asked what we actually built. An agent that occasionally can't reach OpenAI, or returns something that doesn't parse the way we hoped, shouldn't be able to take the feature down with it. Strands made writing the agent side genuinely quick. Keeping it from becoming a single point of failure was the actual work.

## What's still opt-in

All three agents ship behind environment flags, off by default. That's partly caution, partly cost: turning all three on means an LLM call on nearly every user interaction, including the assembly guide, which we deliberately recompute live every time someone opens the report page rather than caching a possibly-stale version. Fine for a hackathon demo. Past that, "rule-based always on, agent opt-in per feature" is probably staying the shape of this app going forward, agents included.
