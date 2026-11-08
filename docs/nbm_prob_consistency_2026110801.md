# NBM probability vs percentile consistency

NBM 2026110801: probability fields vs percentile-implied P(>x), western US cells (every 2nd)

| Window | End | Threshold | Cells | mean abs diff (pts) | median diff (prob - implied) | within 10 pts | corr |
|---|---|---|---|---|---|---|---|
| 24 h | f029 | >0.1 in | 1,185 | 7.2 | -0.8 | 75 % | 0.92 |
| 24 h | f029 | >1.0 in | 502 | 4.0 | +1.0 | 93 % | 0.96 |
| 24 h | f029 | >2.0 in | 251 | 3.8 | +1.0 | 92 % | 0.96 |
| 24 h | f029 | >4.0 in | 96 | 4.0 | +1.0 | 90 % | 0.96 |
| 24 h | f131 | >0.1 in | 2,681 | 1.5 | -1.2 | 100 % | 0.87 |
| 24 h | f131 | >1.0 in | 1,347 | 1.1 | +0.0 | 100 % | 0.87 |
| 24 h | f131 | >2.0 in | 867 | 0.9 | +0.0 | 100 % | 0.85 |
| 24 h | f131 | >4.0 in | 589 | 0.9 | +0.8 | 100 % | 0.83 |
| 24 h | f131 | >6.0 in | 402 | 0.9 | +1.0 | 100 % | 0.77 |
| 24 h | f131 | >8.0 in | 284 | 0.9 | +1.0 | 100 % | 0.73 |
| 24 h | f131 | >10.0 in | 197 | 0.7 | +1.0 | 100 % | 0.69 |
| 24 h | f131 | >12.0 in | 108 | 0.6 | +1.0 | 100 % | 0.72 |
| 48 h | f107 | >1.0 in | 1,064 | 3.6 | +3.1 | 98 % | 0.91 |
| 48 h | f107 | >2.0 in | 514 | 3.1 | +3.0 | 99 % | 0.87 |
| 48 h | f107 | >4.0 in | 96 | 2.5 | +1.0 | 97 % | 0.90 |
| 72 h | f077 | >1.0 in | 1,670 | 4.0 | +2.9 | 94 % | 0.92 |
| 72 h | f077 | >4.0 in | 197 | 3.6 | +1.0 | 90 % | 0.96 |
| 72 h | f077 | >6.0 in | 59 | 8.0 | +1.0 | 71 % | 0.93 |
| 72 h | f179 | >1.0 in | 20,223 | 2.0 | +0.3 | 98 % | 0.94 |
| 72 h | f179 | >4.0 in | 12,541 | 1.5 | +0.8 | 99 % | 0.94 |
| 72 h | f179 | >6.0 in | 9,806 | 1.3 | +1.0 | 100 % | 0.95 |
| 72 h | f179 | >8.0 in | 7,959 | 1.3 | +1.0 | 100 % | 0.95 |
| 72 h | f179 | >12.0 in | 5,405 | 1.2 | +1.0 | 100 % | 0.95 |
| 72 h | f179 | >18.0 in | 3,148 | 1.0 | +1.0 | 100 % | 0.95 |
| 72 h | f179 | >24.0 in | 1,931 | 1.0 | +1.0 | 100 % | 0.94 |
| 72 h | f179 | >30.0 in | 1,365 | 1.0 | +1.0 | 100 % | 0.93 |
| 72 h | f179 | >36.0 in | 1,076 | 1.1 | +1.0 | 100 % | 0.89 |
| 72 h | f179 | >48.0 in | 735 | 1.1 | +1.0 | 100 % | 0.79 |

Method: `tools/nbm_prob_consistency.py`; P(>x) implied by the 15 percentile levels (linear
between levels) vs NBM's probability field, over western cells whose 99th percentile is at
least half the threshold. Result: the two NBM products agree to a few points; the probability
fields run ~1 point higher. Worst agreement: P(>0.1 in) in the first day (75 % within 10 pts).
