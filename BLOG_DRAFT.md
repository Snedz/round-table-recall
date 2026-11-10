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
Numbers from `python -m rtr trust` on Mon Nov 9, 7:13 PM ET (America/Toronto),
after 1 evening NIM run plus 5 OpenRouter runs. 66 memories on Walrus Mainnet.

| Seat  | n | mean score | weight |
|-------|---|------------|--------|
| atlas | 6 | 9.0 | 1.60 |
| orion | 6 | 8.5 | 1.52 |
| vega  | 7 | 7.4 | 1.38 |

| Model route that answered | n | mean | weight |
|---------------------------|---|------|--------|
| openrouter:dots-studio/dots-3-note-preview:free | 5 | 9.0 | 1.57 |
| openrouter:nvidia/nemotron-3.5-lightning:free | 5 | 8.8 | 1.54 |
| openrouter:recursive/flint-v1.0:free | 5 | 8.2 | 1.46 |
| nim:minimaxai/minimax-m3.1-flash | 1 | 10.0 | 1.33 |
| nim:stepfun-ai/step-5-preview | 1 | 9.0 | 1.27 |
| nim:nvidia/nemotron-3.5-lightning-30b-a3b | 2 | 4.0 | 0.90 |

| Source domain (top / bottom) | n | mean | weight |
|------------------------------|---|------|--------|
| britannica.com | 5 | 9.0 | 1.57 |
| earthobservatory.nasa.gov | 2 | 9.5 | 1.45 |
| science.nasa.gov | 2 | 9.5 | 1.45 |
| en.wikipedia.org | 4 | 6.2 | 1.17 |
| earthsky.org | 1 | 3.0 | 0.87 |
| universetoday.com | 1 | 2.0 | 0.80 |

- Run 0: every seat starts at weight 1.00.
- After the first scored Mainnet run (Mon Nov 9, 6:33 PM ET, all NIM): orion 1.33, atlas 1.27, vega 0.90. Vega had earlier echoed the prompt template and scored 0; memory kept that.
- After five more runs at 7:02–7:13 PM ET (every seat answered via OpenRouter free): atlas 1.60, orion 1.52, vega 1.38. Source scores now spread (e.g. NASA 8–10, wikipedia ~6, blogs 2–3) instead of all-10.
- Tatum Sui proof at the same time: MemWalAccount active, **50** Walrus Blob objects owned on Mainnet (undercount: the free Tatum tier returned HTTP 429 mid-paging). After adding 429 backoff (Mon Nov 9, 10:33 PM ET): **66** Blob objects, one per memory.

## What's next
The memory layer is a tiny interface (`remember(records)`, `recall()`), so any
multi-model loop can reuse it, for example to remember which reviewer model
catches real bugs in a plan, critique, build, review loop.

Repo: _link once public_ · Demo: _video link_ · Built for Walrus x Tatum "Total Recall".
