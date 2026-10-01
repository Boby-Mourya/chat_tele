# Configurable AI model connections

Agent settings now have one **AI connection** panel. An administrator chooses a
provider, selects a catalog model (or enters a custom model id), chooses the
internet fallback policy, and saves the agent. Provider calls are made by the
API server; browser code never receives or uses an API key.

## Supported providers

- NVIDIA AI Endpoints (Nemotron, Llama, Mistral, Qwen, DeepSeek and Gemma)
- OpenAI
- Anthropic Claude (Messages API)
- Google Gemini (Gemini API)
- Ollama
- Any OpenAI-compatible server, including vLLM, LM Studio and hosted gateways

The catalog is a safe starting list, not a restriction. Use **custom model id**
for a model exposed by a provider that is not listed yet. The provider protocol
and endpoint determine how the request is sent.

## First-time setup

1. Set `CRM_CREDENTIAL_ENCRYPTION_KEY` in the API environment to a unique,
   long random secret. Existing CRM credential storage uses the same server-side
   encryption facility.
2. Open an agent's **Settings → AI connection** panel.
3. Choose a provider, enter its API key and save a named connection. The key is
   encrypted before it is stored in `llm_connections`; it is never returned by
   the API.
4. Select that saved connection and model, choose the internet policy, then save
   the agent.

If a connection is removed or its key cannot be decrypted, the agent returns a
clear provider-unavailable response instead of silently switching providers.

## Local Ollama and compatible servers

The API process must be able to reach the endpoint. When the API runs in Docker
and Ollama runs on the host, use `http://host.docker.internal:11434/v1` rather
than `127.0.0.1`. For a local vLLM/LM Studio server use its OpenAI-compatible
`/v1` base URL, enter the exact model id exposed by that server, and leave the
API key blank unless the server requires one. Local endpoints are permitted only
for Ollama and the custom OpenAI-compatible provider.

## Internet policy

- **Knowledge base only**: retrieval from approved workspace knowledge only.
- **Knowledge + allowlisted sites**: approved knowledge first, then the domains
  configured under Knowledge boundaries.
- **Public web fallback**: approved knowledge first, then permitted web evidence,
  and finally general model knowledge when no evidence is found.

This setting controls the existing bounded web-retrieval path. It does not give
the model arbitrary network or tool access. The older Knowledge boundaries
selector remains for compatibility and is synchronized with the AI connection
selection.

## Code examples

The setup panel shows Python, LangChain and Node examples for the selected
OpenAI-compatible endpoint. They are reference snippets only; Northstar never
executes user-pasted code. Embeddings and document indexing continue to use the
platform's managed embedding configuration, while the selected connection is
used for answer generation and translation.
