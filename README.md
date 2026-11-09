# Round Table Recall

A research agent that **learns which models and sources to trust**, and keeps
that track record in **Walrus Memory** so it carries over from run to run.

Three free-model seats answer a public research question. A critic seat scores
each answer (anonymized and shuffled) and each cited source domain. Every
score becomes a memory on Walrus. The next run recalls those memories, weights
the seats by their record, and picks the answer with the best
`critic score x remembered weight`. The weights change visibly from run to run.

A **proof panel** reads the `MemWalAccount` object and the Walrus `Blob`
objects that back each memory through **Tatum's Sui gateway**, so you can see
the memory exists onchain without trusting this app.

Built for the Walrus x Tatum "Total Recall" hackathon (Smart Agents for Real Life track).

## How it works

```
question ──► seats (atlas, vega, orion) ──► critic (A/B/C, shuffled) ──► scores
   ▲            each seat fails over:                                     │
   │            NVIDIA NIM ⇄ OpenRouter :free ⇄ opencode Zen               ▼
   └── weights ◄── trust ledger ◄── recall ◄── Walrus Memory ◄── remember (bulk)
                                                    │
                          Tatum Sui gateway ──► MemWalAccount + Blob objects (proof)
```

- `rtr/llm.py`: seats as chains of OpenAI-compatible routes, so one exhausted free tier never empties a seat. The route that actually answered is stored with each score.
- `rtr/memory.py`: `MemoryBackend` interface with `JsonlMemory` (local), `WalrusMemory` (official `memwal` SDK, managed relayer) and `MirroredMemory` (Walrus plus a local mirror).
- `rtr/trust.py`: Bayesian track record (prior 5/10 worth 2 runs). A new seat weighs 1.00. A seat that keeps scoring 9 trends toward 1.8, and one that keeps scoring 1 trends toward 0.2.
- `rtr/roundtable.py`: one round: recall, ask, critique, pick, remember.
- `rtr/sui.py`: Tatum Sui GraphQL reads (checkpoint, `MemWalAccount`, owned `::blob::Blob` objects).
- `rtr/web.py`: a one-file demo page (stdlib only).

Each memory is one line, `RTR1 {json}`, with `kind` set to `seat_score`, `source_score` or `run`.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
# credentials: env vars, or files of the same lowercase name in $RTR_SECRETS_DIR
export MEMWAL_ACCOUNT_ID=... MEMWAL_PRIVATE_KEY=...      # Walrus Memory delegate key (never the owner key)
export TATUM_API_KEY_MAINNET=...                         # free Tatum key
export NVIDIA_API_KEY=... OPENROUTER_API_KEY=...         # free model tiers
export RTR_NETWORK=mainnet                               # or testnet

python -m rtr ask "Why is the sky blue?"     # one round, writes memories
python -m rtr ask -n 5                       # 5 built-in public questions
python -m rtr trust                          # track record recalled from Walrus
python -m rtr proof                          # onchain proof via Tatum
python -m rtr serve                          # http://127.0.0.1:8787
python -m rtr --memory jsonl ask ...         # offline: local memory only
pytest -q
```

## Reuse (dual use)

`MemoryBackend` and the trust ledger don't depend on the question format.
Any loop that can emit `{"kind": "seat_score", "seat": ..., "score": ...}`
records gets a cross-run track record for free. Two examples are a multi-model
planning council, and a plan, critique, build, review loop that wants to know
which reviewer models were right last time.

## Data rules

Only public test questions go into memory. The managed relayer sees memory
plaintext (it embeds and Seal-encrypts server-side), so don't store private
data with the default client. Use `MemWalManual` or a self-hosted relayer for
that.

## License

MIT
