# Demo script (2.5 min, screen recording, captions; voice optional)

| t | Screen | Say / caption |
|---|---|---|
| 0:00-0:15 | README diagram | "Round Table Recall: three free AI models answer, a critic grades them, and Walrus Memory remembers who was right." |
| 0:15-0:35 | `python -m rtr trust` | "This is the track record, recalled from Walrus Mainnet, not a local database. Each seat, model and source has a weight." |
| 0:35-1:20 | `python -m rtr ask "Do humans only use 10 percent of their brains?"` | "Weights before the run come from memory. Three seats answer with sources. The critic grades them blind. The winner is critic score times remembered weight." |
| 1:20-1:40 | same output, MEMORY WRITES block | "Every grade is its own Walrus memory. Here are the blob ids, written through the managed relayer for $0." |
| 1:40-2:05 | `python -m rtr proof` (or the web page panel) | "Proof it exists: via Tatum's Sui gateway we read the MemWalAccount and the Walrus Blob objects. The count went up by exactly this run's writes." |
| 2:05-2:25 | run `trust` again | "And the weights moved. Next question, the table trusts the seats that earned it." |
| 2:25-2:30 | repo URL | "Code is open source. Thanks, Walrus and Tatum." |

Before recording: run `python -m rtr ask -n 3` once so the weights differ clearly. Keep only public questions on screen. Don't show any env var or key file.
