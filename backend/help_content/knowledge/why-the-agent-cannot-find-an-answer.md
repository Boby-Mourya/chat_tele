---
slug: why-the-agent-cannot-find-an-answer
title: Why the agent cannot find an answer
summary: Use trusted sources and understand how Northstar retrieves grounded information.
category: knowledge
roles:
- owner
- admin
- member
- analyst
keywords:
- why
- the
- agent
- cannot
- find
- answer
- rag
- source
- retrieval
featured: false
sort_order: 290
---

# Why the agent cannot find an answer

A grounded agent may refuse or say it lacks enough evidence when retrieval cannot find trustworthy support for the question.

## Check these first

1. Open the agent's **Knowledge** tab.
2. Confirm the expected source is **ready**.
3. Verify the source actually contains the requested fact in clear language.
4. Test with a phrase that appears in the source.
5. Check whether the question depends on a different agent's knowledge; knowledge is agent-scoped.
6. Review instructions for accidental restrictions or conflicting guidance.

## What not to do

Do not simply increase model creativity to hide a retrieval problem. That can make unsupported answers more likely.

## Next step

Use **Improve retrieval quality** if the correct source is present but matching remains weak.
