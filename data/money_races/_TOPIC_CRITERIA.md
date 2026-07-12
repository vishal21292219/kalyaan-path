# Money-Race Topic Criteria (viral formula — codified 2026-07-08)

The ACTIVE moneurons pool. `money_race_runner` picks the least-recently-used
`*.json` here (ignore `_`-prefixed files like this one). Legacy text-Shorts pool
`data/viral_topics_moneurons.json` is NOT used by the bar-race pipeline.

## The formula every topic must pass
A **surprising ranking-FLIP over time** — a leaderboard the US money-audience
recognizes, where the order **dramatically changes** (an underdog overtakes a
giant). Static rankings where nothing moves are boring — avoid them.

Proven pull:
- **Tesla $2B → $1T** crushing century-old carmakers (`20_car_companies`)
- **$100/month → $228k vs $38k** same money, different choice (`24_hundred_a_month`)
- **China's military 20 → 360** chasing the US (`19_military`)

Formula = `<a ranking people recognize>` + `<a visible dramatic overtake/gap>` +
`<a "same money, different outcome" / "who's next" punchline in the outro>`.

## Spec (every topic JSON)
```
title       : short ALL-CAPS hook (e.g. "CAR WARS")
subtitle    : year range ("2010 - 2026")
unit        : value prefix ("$" or "")
suffix      : value suffix ("B", "M", "K", "t", or "")
intro       : [2 card lines] — the setup / stakes
outro       : [4 lines] — payoff + CTA; LAST line MUST be "@moneurons"
vo          : full narration string (spoken, spells out numbers as words)
data        : { "<entity>": { "<year>": <number>, ... }, ... }  # ~6-8 entities, ~6-9 year snapshots
```
Keep entities to 6-8 (bars stay readable) and pick year snapshots that show the
overtake clearly. Numbers should be plausible/roughly accurate for credibility.
