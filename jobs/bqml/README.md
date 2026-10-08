# BigQuery ML jam forecast

A boosted-tree regressor (`corridor.jam_forecast`) that predicts the next reading of `jam_m`, the
metres of jammed road on a junction approach, from the current reading and the time of day. Inputs
come from `corridor.traffic_spans`, which the traffic logger job fills from Routes API speed readings.

| File | What it does |
|---|---|
| `features.sql` | View `corridor.traffic_features`: hour, weekday, minute (Asia/Kolkata), junction, approach, corridor, `jam_m`, `slow_m`, `routes_eta_s`, and the label `next_jam_m` (the following row's `jam_m` for the same junction and approach). |
| `train.sql` | `BOOSTED_TREE_REGRESSOR`, `max_iterations=20`, `ts` excluded, unlabelled last rows dropped. |
| `evaluate.sql` | `ML.EVALUATE`. |
| `predict.sql` | `ML.PREDICT` for every junction and approach, four 15-minute buckets ahead, holding the latest observed readings fixed. |
| `run.sh` | Runs the four in order with `bq`. Training takes about 15 minutes. |

## What it is not

This is a proof of the pipeline, not a forecast to deploy. The logger runs on Cloud Scheduler for
Bengaluru peak hours since 6 Oct (paused after 10 Oct), and a retrain on whatever has
accumulated is scheduled before submission. The first model was trained on the earlier 216 rows (187 labelled),
logged for about 50 minutes at midnight on 2026-10-05 across 29 junction approaches in two
corridors, before peak-hour collection began. There is no daily pattern to learn in 50 minutes.

Worse, `jam_m` is 0 in every one of those rows, so the label is constant. The model learned to
predict about zero and nothing else, which is why the numbers below look excellent and mean nothing:
R2 is `-Infinity` because the label has no variance. Traffic was free-flowing at the logged hours (`slow_m` is non-zero in only a few rows).
Peak-hour collection is the fix, but a few days of it is still not a daily or weekly pattern: it will
only start to say something after weeks that include real congestion. The evaluation also scores the
same rows the model trained on: with fewer than 500 rows BigQuery ML keeps the whole table for training.

Boosted trees ran without complaint on this data, so no `LINEAR_REG` fallback was needed.

## Results (first model, constant label, 2026-10-06; superseded by the retrain below)

`ML.EVALUATE`:

| mean_absolute_error | mean_squared_error | mean_squared_log_error | median_absolute_error | r2_score | explained_variance |
|---|---|---|---|---|---|
| 4.18e-4 | 1.74e-7 | 1.74e-7 | 4.18e-4 | -Infinity | NaN |

Three sample predictions from `predict.sql` (bucket times are UTC; every prediction is the same constant):

| junction_id | approach | bucket_ts | predicted_next_jam_m |
|---|---|---|---|
| blr_j1 | E | 2026-10-05 21:54:00 | 4.18e-4 |
| blr_j1 | NW | 2026-10-05 22:09:00 | 4.18e-4 |
| blr_j1 | SE | 2026-10-05 22:24:00 | 4.18e-4 |

## Retrain 2026-10-08

Retrained on `corridor.traffic_spans` after the peak-hour collection that began on 6 Oct. The table holds
2,173 rows, 5 Oct 23:20 to 8 Oct 10:50 IST (17:50 to 05:20 UTC); 1,993 are from 6 Oct onward and 1,849 fall in
the peak hours (08:00-10:59 and 17:00-20:59 IST). 2,144 are labelled, so that is the training set.

**`jam_m` is still mostly zero.** Only 267 of 2,173 rows (12.3%) have `jam_m` above zero, so 87.7% are zeros. Inside the
peak hours it is 265 of 1,849 (14.3%). Mean `jam_m` by hour is 17 m at 08:00, 47-48 m at 09:00-10:00, 64 m at 17:00,
78 m at 18:00, 57 m at 19:00 and 17.5 m at 20:00 IST, with a maximum of 602 m. Midnight to 05:00 readings are all zero.
The earlier caveat stands: this is a few days of data, not a weekly pattern, and congestion is rare in it.

What the model does: it forecasts the next reading of `jam_m` for each junction and approach from the current
`jam_m`, `slow_m` and Routes ETA plus hour of day, day of week and minute. It is a baseline.

`ML.EVALUATE` (BigQuery ML's automatic split, since there are more than 500 rows: random 80/20, so rows from the same
series sit on both sides and the score is optimistic):

| mean_absolute_error | mean_squared_error | mean_squared_log_error | median_absolute_error | r2_score | explained_variance |
|---|---|---|---|---|---|
| 29.81 | 5847.87 | 3.50 | 3.20 | 0.581 | 0.585 |

For scale, predicting zero everywhere scores a mean absolute error of 39.0 m (the mean label) and repeating the
current `jam_m` as the next value scores 21.8 m across all labelled rows. So the model beats a constant zero but
does not beat plain persistence on mean absolute error. Treat the R2 as evidence that the pipeline learns the
current reading and not as a forecast skill. The model is not deployed.

Three sample predictions from `predict.sql` (bucket times are UTC; 06:12 UTC is 11:42 IST, off-peak, and the latest
observed readings are held fixed):

| junction_id | approach | bucket_ts | predicted_next_jam_m |
|---|---|---|---|
| blr_j1 | E | 2026-10-08 06:12:00 | 0.62 |
| blr_j1 | NW | 2026-10-08 06:12:00 | 0.90 |
| hyd_j2 | NE | 2026-10-08 06:12:00 | 488.30 |

The `hyd_j2` row is high because that approach's latest reading was a long jam and the prediction holds it fixed.
Training took about 11 minutes.

## From jam forecast to clearance-rate model

Every run ends with a report card in BigQuery (`corridor.run_reports`). Once enough of them
accumulate, the same recipe applies with a different label: join each run's report card to the
traffic features at the junctions it crossed and train a model for how fast a queue clears after a
green is granted, given queue length, time of day and approach. That model is what sizes the PREPARE and STOP CROSS TRAFFIC
alerts. The jam forecast here supplies the "how bad will it be when the vehicle arrives" input to
it. The view, `CREATE MODEL`, evaluate and predict steps stay the same; only the label and
the join change.
