<!-- DRAFT ONLY. Not published. Needs Snowden's yes on the exact text and where it goes. -->
# Round Table Recall: a research agent that remembers who to trust

**TL;DR:** I built a research round table of three free AI models plus a critic.
Every score the critic gives is stored in Walrus Memory on Sui Mainnet, and the
next question is weighted by that remembered track record. A proof panel reads
the memory's onchain objects through Tatum's Sui gateway.

## The problem
Multi-model "councils" are great at disagreeing and bad at remembering. Every
run starts from zero: the model that was wrong yesterday gets the same vote
today. Which model, and which source, has earned trust is exactly the context
that gets lost between sessions.

## What it does
1. Three seats (each a chain of free models across NVIDIA NIM, OpenRouter and
   opencode Zen) answer a public research question and cite up to 3 URLs.
2. A critic seat grades the answers anonymized and shuffled, 0-10, and grades
   each cited source domain.
3. Each grade becomes its own memory (`seat_score`, `source_score`, `run`) via
   the Walrus Memory Python SDK and the managed Mainnet relayer.
4. The next run recalls those memories, computes a Bayesian track record per
   seat, and picks the answer with the best `critic score x remembered weight`.

## How it uses Walrus
- `remember_bulk_and_wait` writes up to 20 memories per call. Each one is
  Seal-encrypted and stored as its own Walrus blob, owned by my Sui address.
- `recall` brings the track record back on any machine that holds the delegate
  key. There's no app database to lose, and `restore` can rebuild the index
  from the blobs.

## How it uses Tatum
The proof panel uses Tatum's Sui gateway (GraphQL) to read the latest
checkpoint, the `MemWalAccount` object (owner, delegate keys, active flag) and
every `::blob::Blob` object the owner holds. That shows the memory exists
independently of the relayer that wrote it.

## How it learned over time
<!-- fill with real numbers from `python -m rtr trust` right before publishing -->
- Run 1: all seats start at weight 1.00.
- After the first scored run (Mon Nov 9, 6:33 PM ET): orion 1.33, atlas 1.27,
  vega 0.90. Vega had earlier echoed the prompt template and scored 0, and the
  memory kept that.
- After N runs: _table from `rtr trust`_.

## What's next
The memory layer is a tiny interface (`remember(records)`, `recall()`), so any
multi-model loop can reuse it, for example to remember which reviewer model
catches real bugs in a plan, critique, build, review loop.

Repo: _link once public_ · Demo: _video link_ · Built for Walrus x Tatum "Total Recall".
