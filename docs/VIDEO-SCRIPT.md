# Demo video: script and how to record (target 2:45, limit 3:00)

## How to record (free, Mac)
1. Run the stack: `make db`, `SINEW_LOCAL=1 make api`, `make web`. Open Chrome full screen at 1440×900, hide bookmarks.
2. Press **Cmd+Shift+5** → "Record Entire Screen" (or "Record Selected Portion" around the browser) → Options → microphone: your Mac mic → Record. Stop with the menu-bar stop button. The file lands on the Desktop as .mov.
3. Do one dry run with `SINEW_AI=off` to know the clicks, then record with the AI on. Each question uses 2 of the 450 daily calls, so there is plenty of quota.
4. Record in short takes (one scene each) and join them in QuickTime (Edit → Add Clip to End) or iMovie. Speak slowly; no music needed.
5. Upload to YouTube as "Unlisted" and paste the link in the submission.
6. Reset the data before the take: profile menu → **Reset demo data**.

## Script

| Time | On screen | Say |
|---|---|---|
| 0:00–0:15 | Title: "Sinew · company brain" | "A company's answers live in many systems. Sinew puts them in one FalkorDB graph and answers by walking it, only showing what your role may see." |
| 0:15–1:10 | Sign in as **Daniel (CEO)**. Ask: *Why are complaints up this week, and what should we do?* Open **How Sinew knows** and scroll to the Cypher. | "Complaints are up. Sinew follows ticket, order, parcel, hub, to a decision. Courier Y was assumed 90% on time at Hub W2; it's 77%. A flash sale pushed 1.57 times the hub's capacity through it. The Winter Sale uses the same hub, and Sinew finds a reroute through W4. Here is the path and the exact Cypher that ran. The model fills a spec; our code validates it against the schema and the role, and writes the Cypher itself." |
| 1:10–1:50 | Sign in as **Chloe** (brand marketer): *What does Courier Y cost per parcel?* → refused. Sign in as **Priya** (CMO): same question → $4.20. | "Same question, two roles. Permissions are edges in the graph, enforced in code, so the marketer is refused and the CMO gets the number." |
| 1:50–2:25 | Sign in as **Ravi** (support, west): *Which of my customers are waiting longest for a refund?* | "A support agent sees his own region's customers by name; for anyone else it would be counts only. No names are stored in the graph: personal data is fetched live, only for allowed roles." |
| 2:25–2:45 | Show Home for two roles side by side, then the README graph table. | "Each role gets its own home screen. FalkorDB does real work here: WCC for identity, label propagation for incidents, PageRank for decisions, shortest path for reroutes. Checked against the source data: 26 of 26 totals match. Code and setup are in the repo." |

## If the AI misbehaves during a take
**Expect it.** Before the 18 Oct fixes the free planner failed those two scenes about half the time; after them 15 of 16 runs were right. The free model is still not perfectly steady, so keep the retake advice below. For those two scenes:
- Open **+ New chat** and ask again until the answer appears, and cut the failed tries when you edit (each try is a real, separate answer; do not claim it worked first time). Or run the scene as a dry run first and only record once it answers.
- Use exactly the wording above; rewording made it worse.
- If you get the plain graph draft (correct but mechanical), say "this is the graph's own answer" and keep going.
- The labels in the app are checked: "+ New chat", "How Sinew knows" (click to open), "What to do", "Sources", "Tell the decision owner". The refusal text is "That's outside your access."

Screenshots of each scene (taken from the running app) are in `docs/img/` if you want stills for the video or the submission page.
