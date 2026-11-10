# Round Table Recall

A research agent that **learns which models and sources to trust**, and keeps
that track record in **Walrus Memory** on Sui Mainnet so it carries over from run to run.

- **Memory changes what it does.** When we told the seats to avoid two domains the critic
  had rated low, the smallest model cited exactly those domains (one URL looked made up).
  Naming them had primed it. So remembered low-trust sources are now also **stripped
  before grading**, weak models are demoted, and weak seats go on probation.
- **Forget the local copy and nothing is lost.** `python -m rtr amnesia` ignores the local
  mirror, rebuilds the ledger from Walrus recall alone (126 memories) and compares it with
  every write ever made (161): **0 differences**, same seat weights, same next-run changes.
  Then Tatum confirms **126/126** recalled memories are Walrus Blob objects onchain
  ([`preview/amnesia.log`](preview/amnesia.log)).
- **Verify it with no account.** `python -m rtr proof` reads the MemWalAccount and all
  **161** Walrus Blob objects through Tatum's Sui gateway **without an API key** (anonymous
  plan, ~1 min), and cross-checks the account over Tatum gRPC
  ([`preview/proof-keyless.log`](preview/proof-keyless.log)). Every blob id links to Walruscan.

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

**Verify it yourself, no trust in this app and no Tatum account needed:** the account id is public, so run
`MEMWAL_ACCOUNT_ID=<account id from the submission> python -m rtr proof`.
Without a key it uses Tatum's anonymous plan and backs off on HTTP 429 (about a minute); with
`TATUM_API_KEY_MAINNET=<your free key>` it is faster. Sui JSON-RPC on the Tatum gateway returns 404,
so nothing here uses it.

A **proof panel** reads the `MemWalAccount` object and the Walrus `Blob`
objects that back each memory through **Tatum's Sui gateway**, so you can see
the memory exists onchain without trusting this app. Blob ids open on
[Walruscan](https://walruscan.com/mainnet/blob/pGiD_Lrwu_Fc0NVoiE1pSI-n123Nr6ydp3Kzl-dJSJY) (that one is a
memory written in the recorded run), and the MemWal package opens on
[Suiscan](https://suiscan.xyz/mainnet/object/0xe7c16fbea0560e7057e2bf7422feaa4fb313749fc69c9e9092fac7a33b81d7f5).

**Amnesia test.** Walrus recall returns at most ~100 results per query, and 161 memories exist.
`python -m rtr amnesia` shows that does not matter: the newest ledger snapshot plus newer scores,
recalled from Walrus alone, rebuild exactly the ledger the full local mirror gives (seats, models,
56 source domains, seat weights, route order, probation and the distrusted-domain list). It then
checks through Tatum that every recalled memory's blob is owned onchain. It only calls `recall` and
Tatum reads; nothing is written. It needs the delegate key, so judges can read the recorded result in
`preview/amnesia.log`.

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
- `rtr/sui.py`: Tatum Sui GraphQL reads (checkpoint, `MemWalAccount`, owned `::blob::Blob` objects); API key optional. Walruscan/Suiscan links.
- `rtr/sui_grpc.py`: Tatum Sui gRPC (`LedgerService.GetServiceInfo`, `GetObject`) via reflection, used as a cross-check; API key optional.
- `rtr/amnesia.py`: rebuild the ledger from Walrus alone, diff it against the local mirror, check every recalled blob onchain via Tatum.
- `rtr/web.py`: a one-file demo page (stdlib only).

Each memory is one line, `RTR1 {json}`, with `kind` set to `seat_score`, `source_score`, `run` or `ledger`.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt   # or: pip install .

# no keys needed: replay a recorded Mainnet run (the judge-safe path)
python -m rtr replay                         # transcript + Tatum proof from 2026-11-09 23:56 ET
python -m rtr serve --replay                 # http://127.0.0.1:8787, live ask off

# credentials for a live run: env vars, or files of the same lowercase name in $RTR_SECRETS_DIR
export MEMWAL_ACCOUNT_ID=... MEMWAL_PRIVATE_KEY=...      # Walrus Memory delegate key (never the owner key)
export TATUM_API_KEY_MAINNET=...                         # free Tatum key (optional for proof/amnesia)
export NVIDIA_API_KEY=... OPENROUTER_API_KEY=...         # free model tiers
export RTR_NETWORK=mainnet                               # or testnet

python -m rtr ask "Why is the sky blue?"     # one round, writes memories
python -m rtr ask -n 5                       # 5 built-in public questions
python -m rtr trust                          # track record recalled from Walrus
python -m rtr proof                          # onchain proof via Tatum (works with no Tatum key)
python -m rtr amnesia                        # rebuild the ledger from Walrus alone; read-only
python -m rtr serve                          # http://127.0.0.1:8787
python -m rtr snapshot --last-run preview/replay-run.txt --proof preview/proof-keyless.log --amnesia preview/amnesia.log   # static docs/index.html
python -m rtr --memory jsonl ask ...         # offline: local memory only
pytest -q                                    # 27 tests, no network
```

## Evidence in this repo

- `preview/run*.log`: real Mainnet runs, including the `MEMORY CHANGED THIS RUN` blocks and Tatum receipts.
  `run5b-priming.log` is the run where a small model cited the very domains it was told to avoid, which is
  why distrusted sources are now stripped before grading (`run6-strip-check.log`).
- `preview/trust6.log`: the recalled track record and learning curve. `preview/proof6.log`: the Tatum
  GraphQL proof (161 Blob objects) plus the gRPC cross-check. `preview/proof-keyless.log`: the same proof
  with no Tatum API key. `preview/amnesia.log`: the amnesia test (0 differences, 126/126 blobs onchain).
  `preview/tatum_gateway_methods.txt`: what the Tatum Sui gateway exposes.
- `preview/replay-run.txt`: the recorded Mainnet run used by `python -m rtr replay` and `python -m rtr serve --replay` (147→161 blobs, all three seats, Tatum receipt matched).
- `docs/index.html`: a static, read-only snapshot of the demo page (recorded run, keyless proof, amnesia test; blob ids link to Walruscan).

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
