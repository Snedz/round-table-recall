# Round Table Recall

A research agent that **learns which models and sources to trust**, and keeps
that track record in **Walrus Memory** so it carries over from run to run.

Three free-model seats answer a public research question. A critic seat scores
each answer (anonymized and shuffled) and each cited source domain. Every
score becomes a memory on Walrus. The next run recalls those memories, weights
the seats by their record, and picks the answer with the best
`critic score x remembered weight`. The weights change visibly from run to run.

Memory also changes **what the table does**, not only who wins. Before each run it
recalls the ledger and prints a `MEMORY CHANGED THIS RUN` block:

- **Model routes with a below-average record get demoted.** A free model the critic
  kept scoring low moves to the back of its seat's failover chain.
- **A seat with a bad record goes on probation.** If a seat's own weight falls below
  0.80, its usual first model is swapped for the next one in its chain for that run.
- **Low-trust sources get named in the prompt, and removed if cited anyway.** Domains
  the critic rated below an unknown source are listed for every seat to avoid. Any
  that a seat still cites are stripped from its answer before the critic grades it,
  and the run says which seat did it.
- **The ledger never forgets.** Each run also stores one `ledger` snapshot memory
  (running sums and counts per seat, model and domain). The track record is
  rebuilt from *latest snapshot + newer scores*, so it stays complete well past the
  100-result recall window.

After every Mainnet run the CLI re-reads the owner's Walrus `Blob` objects through
Tatum and prints a **Tatum receipt**: the blob count before and after the run, and
whether the increase matches this run's memory writes.

`python -m rtr proof` uses **both Sui interfaces Tatum's gateway exposes**: GraphQL
(`sui-mainnet.gateway.tatum.io/graphql`, the only interface its `/_methods` lists;
Sui JSON-RPC there returns 404) for the account and blob objects, and gRPC
(`sui.rpc.v2.LedgerService` on `sui-mainnet-grpc.gateway.tatum.io`, message types via
server reflection) to cross-check that the `MemWalAccount` version and digest match.

**Verify it yourself, no trust in this app needed:** the account id is public, so with
your own free Tatum key run
`MEMWAL_ACCOUNT_ID=<account id from the submission> TATUM_API_KEY_MAINNET=<your key> python -m rtr proof`.

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
- `rtr/trust.py`: Bayesian track record (prior 5/10 worth 2 runs). A new seat weighs 1.00. A seat that keeps scoring 9 trends toward 1.8, and one that keeps scoring 1 trends toward 0.2. Ledger snapshots, demoted routes, distrusted sources.
- `rtr/roundtable.py`: one round: recall, plan (memory effects), ask, critique, pick, remember (+ snapshot).
- `rtr/adapters.py`: turns a Borda-style council ranking from another round table into ledger records.
- `rtr/sui.py`: Tatum Sui GraphQL reads (checkpoint, `MemWalAccount`, owned `::blob::Blob` objects).
- `rtr/sui_grpc.py`: Tatum Sui gRPC (`LedgerService.GetServiceInfo`, `GetObject`) via reflection, used as a cross-check.
- `rtr/web.py`: a one-file demo page (stdlib only).

Each memory is one line, `RTR1 {json}`, with `kind` set to `seat_score`, `source_score`, `run` or `ledger`.

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
python -m rtr snapshot --last-run preview/run6-strip-check.log --proof preview/proof6.log   # static docs/index.html
python -m rtr --memory jsonl ask ...         # offline: local memory only
pytest -q                                    # 20 tests, no network
```

## Evidence in this repo

- `preview/run*.log`: real Mainnet runs, including the `MEMORY CHANGED THIS RUN` blocks and Tatum receipts.
  `run5b-priming.log` is the run where a small model cited the very domains it was told to avoid, which is
  why distrusted sources are now stripped before grading (`run6-strip-check.log`).
- `preview/trust6.log`: the recalled track record and learning curve. `preview/proof6.log`: the Tatum
  GraphQL proof (161 Blob objects) plus the gRPC cross-check. `preview/tatum_gateway_methods.txt`: what the
  Tatum Sui gateway exposes.
- `docs/index.html`: a static, read-only snapshot of the demo page.

## Reuse (dual use)

`MemoryBackend` and the trust ledger don't depend on the question format.
Any loop that can emit `{"kind": "seat_score", "seat": ..., "score": ...}`
records gets a cross-run track record for free. `rtr.adapters.council_records`
already converts an llm-council style peer ranking (answers, anonymized ranking,
chairman) into ledger records. Other examples are a plan, critique, build,
review loop that wants to know which reviewer models were right last time, or a
deadline tracker that remembers which kinds of deadline it let slip.

## Data rules

Only public test questions go into memory. The managed relayer sees memory
plaintext (it embeds and Seal-encrypts server-side), so don't store private
data with the default client. Use `MemWalManual` or a self-hosted relayer for
that.

## License

MIT
