# Round Table Recall: a research agent that remembers who to trust

**TL;DR:** I built a research round table: three free AI models answer, a blind
critic grades them, and every grade is stored in **Walrus Memory on Sui Mainnet**.
The next run recalls that track record, and it changes what the table *does*:
the winner is weighted by remembered trust, weak models get demoted or put on
probation, and low-trust sources are named for every seat to avoid. A proof panel
reads the memory's onchain objects through **Tatum's Sui gateway** (GraphQL plus a
gRPC cross-check), and every run ends with a Tatum receipt showing the blob count
went up by exactly the number of memories written. Then I made it forget: with the
local copy ignored, the ledger rebuilt from Walrus alone matched every write ever
made, with zero differences, and Tatum found every recalled memory onchain. Anyone can
re-check the onchain part without even a Tatum account.

## The problem
Multi-model "councils" are great at disagreeing and bad at remembering. Every
run starts from zero: the model that was wrong yesterday gets the same vote
today. Which model, and which source, has earned trust is exactly the context
that gets lost between sessions.

That's a real-life problem for me, not a toy one. I run a planning loop where
several free models draft, critique and review each other's work. I
want the loop to remember which reviewer caught real problems last week and which
sources kept turning out to be weak, without keeping that in one app's database.

## What it does
1. Three seats (each a failover chain of free models across NVIDIA NIM,
   OpenRouter and opencode Zen) answer a public research question and cite up to
   3 URLs.
2. A critic seat grades the answers anonymized and shuffled, 0-10, and grades
   each cited source domain.
3. Each grade becomes its own memory (`seat_score`, `source_score`, `run`) via
   the Walrus Memory Python SDK and the managed Mainnet relayer, plus one
   `ledger` snapshot per run.
4. The next run recalls those memories, computes a Bayesian track record per
   seat, model and source, and lets that record steer the run.

## How memory changes the product
Before anyone answers, the table prints a `MEMORY CHANGED THIS RUN` block:

- **Sources it learned to distrust are named in every prompt, and removed if
  cited anyway.** The critic had scored universetoday.com and earthsky.org below
  an unknown source, so later prompts told every seat not to cite them. Most runs
  came back clean. But on two questions (goldfish memory, bulls and red), the
  smallest model cited exactly those two domains, and one URL looked made up
  (`universetoday.com/12345/...`). Naming the domains had primed it. So the table
  now strips any distrusted source from an answer before the critic grades it,
  and the run log says which seat did it.
- **Models with a below-average record move to the back** of their seat's
  failover chain.
- **A seat whose weight drops below 0.80 goes on probation**, and its usual
  model is swapped out for that run.
- **The final pick is `critic score x remembered weight`**, so a seat that has
  been right for weeks beats a lucky newcomer on a tie.

Recall only returns about 100 memories at a time, and I passed 100 tonight. A
naive ledger would have started quietly forgetting its oldest runs. So each run
also stores one `ledger` memory with running sums and counts, plus the
learning curve. The track record is rebuilt from *newest snapshot + newer
scores*. I checked it against a local mirror of every write: same counts
(atlas 15, vega 16, orion 12 scored answers after 17 runs).

## How it uses Walrus
- `remember_bulk_and_wait` writes up to 20 memories per call. Each one is
  Seal-encrypted and stored as its own Walrus blob, owned by my Sui address.
- `recall` brings the track record back on any machine that holds the delegate
  key. Three queries are merged: the main semantic query, a `sort="recent"`
  query that always includes the newest ledger snapshot, and a run-summary
  query for the learning curve. There's no app database to lose.
- Cost: $0. The managed relayer covers WAL storage and SUI gas.

## How it uses Tatum
- **GraphQL** on `sui-mainnet.gateway.tatum.io/graphql`, the Sui interface the
  gateway's `/_methods` lists, reads the latest checkpoint, the `MemWalAccount`
  object (owner, delegate keys, active flag) and every `::blob::Blob` object the
  owner holds. It backs off on HTTP 429 so the free tier's 3 requests a second
  don't undercount.
- **gRPC** on `sui-mainnet-grpc.gateway.tatum.io` (`sui.rpc.v2.LedgerService`,
  message types from server reflection) re-reads the account object. Its
  version and digest must match the GraphQL read.
- **Per-run receipt.** After every Mainnet run the CLI re-counts the Blob
  objects through Tatum, for example "Walrus Blob objects 127 -> 135 (+8); 8
  memory writes this run; matches".

Anyone can verify it without trusting the app, and without a Tatum account. The
account id is public, and Tatum's Sui GraphQL answers without an API key on its
anonymous plan, so `MEMWAL_ACCOUNT_ID=<id> python -m rtr proof` reads the account
and all 161 blobs (about a minute, because it backs off on HTTP 429). The gRPC
cross-check also ran keyless. One honest note: the docs list Sui JSON-RPC, but on
the gateway it returns 404 with or without a key, so I didn't use it. GraphQL plus
gRPC is what works today. Every blob id in the output links to Walruscan.

## How it learned over time
All times are Mon Nov 9 2026, ET. The learning curve below is recalled from
Walrus. Each row shows the seat weights going into a run.

| run (ET) | atlas | orion | vega | winner |
|---|---|---|---|---|
| 6:28 PM | 1.00 | 1.00 | 1.00 | vega (only seat that answered; scored 0) |
| 6:32 PM | 1.00 | 1.00 | 0.67 | (no scored answers) |
| 7:04 PM | 1.27 | 1.33 | 0.90 | atlas |
| 7:12 PM | 1.63 | 1.49 | 1.38 | orion |
| 11:23 PM | 1.64 | 1.58 | 1.44 | orion |
| 11:46 PM | 1.74 | 1.62 | 1.53 | atlas |
| 11:58 PM | 1.75 | 1.65 | 1.53 | atlas |

- Run 0: every seat starts at 1.00.
- Vega's first answer (6:28 PM) echoed the prompt template and scored 0. Memory kept
  that: vega went into the next runs at 0.67 and had to earn its weight back.
- Source trust spread out: britannica.com 1.66 (n=9), NIH/NCBI 1.60, NASA Earth
  Observatory 1.52, while healthline.com fell to 0.93, earthsky.org to 0.88 and
  universetoday.com to 0.75.
- The model table records which free model actually answered. When the
  OpenRouter and Zen free quotas ran out at night, the seats failed over to NVIDIA
  NIM models, and those models built their own records.
- Tatum proof at the end: MemWalAccount active, **161 Walrus Blob objects
  owned on Mainnet**, one per memory, and the gRPC read of the account agrees
  with the GraphQL read (same version and digest).

## Forgetting on purpose: the amnesia test
A memory layer is only worth something if you can lose the local copy. So
`python -m rtr amnesia` ignores the local mirror and rebuilds the whole ledger from
Walrus recall alone. Then it compares the result with the mirror, which holds
every memory ever written:

```
  Walrus-only recall       : 126 memories
  local mirror (all writes): 161 memories
  newest ledger snapshot   : 2026-11-09 23:58 EST, covering 17 runs

  rebuilt ledger             walrus  mirror
    seats                       3       3
    models                      7       7
    sources                    56      56
  seat weights (walrus)    : atlas=1.753, vega=1.533, orion=1.643
  what memory changes next run (rebuilt from Walrus):
    - told every seat to avoid 3 low-trust domains: universetoday.com, earthsky.org, healthline.com
  differences vs mirror    : 0, identical

  TATUM CHECK: 126/126 recalled memories are Walrus Blob objects onchain (161 owned by the account owner) (Tatum GraphQL, no API key)
```

Walrus only returned 126 of the 161 memories, and that's fine. The ledger snapshot
plus newer scores carry the rest. Every seat, model and source domain comes back
with the same count and weight, and the next run would change in exactly the same
way. The check only calls `recall` and Tatum reads, and writes nothing. The full
output is `preview/amnesia.log` in the repo.

## Try it
```bash
git clone https://github.com/Snedz/round-table-recall && cd round-table-recall
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m rtr replay                                    # the recorded Mainnet run, no keys
MEMWAL_ACCOUNT_ID=<account id> python -m rtr proof      # onchain proof via Tatum, no key needed
pytest -q                                               # 27 tests, no network
```

## What's next
The memory layer is a tiny interface (`remember(records)`, `recall()`), so any
multi-model loop can reuse it. `rtr.adapters.council_records` already turns an
llm-council style peer ranking into ledger records, so a planning council can
remember which reviewer models catch real problems.

Repo: https://github.com/Snedz/round-table-recall · Demo video: https://youtu.be/CuF0kfMDOK8 · Live snapshot: https://snedz.github.io/round-table-recall/ · Built for Walrus x Tatum "Total Recall".
