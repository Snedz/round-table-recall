<!-- Draft of the blog post. Every number comes from the real run logs in preview/. -->
# Round Table Recall: a research agent that remembers who to trust

**TL;DR:** I built a research round table: three free AI models answer, a blind
critic grades them, and every grade is stored in **Walrus Memory on Sui Mainnet**.
The next run recalls that track record, and it changes what the table *does*:
the winner is weighted by remembered trust, weak models get demoted or put on
probation, and low-trust sources are named for every seat to avoid. A proof panel
reads the memory's onchain objects through **Tatum's Sui gateway** (GraphQL plus a
gRPC cross-check), and every run ends with a Tatum receipt showing the blob count
went up by exactly the number of memories written.

## The problem
Multi-model "councils" are great at disagreeing and bad at remembering. Every
run starts from zero: the model that was wrong yesterday gets the same vote
today. Which model, and which source, has earned trust is exactly the context
that gets lost between sessions.

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

Anyone can verify it without trusting the app. The account id is public, so
run `python -m rtr proof` with your own free Tatum key.

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

## What's next
The memory layer is a tiny interface (`remember(records)`, `recall()`), so any
multi-model loop can reuse it. `rtr.adapters.council_records` already turns an
llm-council style peer ranking into ledger records, so a planning council can
remember which reviewer models catch real problems.

Repo: https://github.com/Snedz/round-table-recall · Demo video: _link once uploaded_ · Live snapshot: _GitHub Pages link if enabled_ · Built for Walrus x Tatum "Total Recall".
