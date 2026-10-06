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
Bengaluru peak hours since 6 Oct (paused after 10 Oct), and the model is retrained on whatever has
accumulated before submission. The first model was trained on the earlier 216 rows (187 labelled),
logged for about 50 minutes at midnight on 2026-10-05 across 29 junction approaches in two
corridors, before peak-hour collection began. There is no daily pattern to learn in 50 minutes.

Worse, `jam_m` is 0 in every one of those rows, so the label is constant. The model learned to
predict about zero and nothing else, which is why the numbers below look excellent and mean nothing:
R2 is `-Infinity` because the label has no variance. Traffic was free-flowing at the logged hours (`slow_m` is non-zero in only a few rows).
Peak-hour collection is the fix, but a few days of it is still not a daily or weekly pattern: it will
only start to say something after weeks that include real congestion. The evaluation also scores the
same rows the model trained on: with fewer than 500 rows BigQuery ML keeps the whole table for training.

Boosted trees ran without complaint on this data, so no `LINEAR_REG` fallback was needed.

## Results (first model, constant label, 2026-10-06)

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

## From jam forecast to clearance-rate model

Every run ends with a report card in BigQuery (`corridor.run_reports`). Once enough of them
accumulate, the same recipe applies with a different label: join each run's report card to the
traffic features at the junctions it crossed and train a model for how fast a queue clears after a
green is granted, given queue length, time of day and approach. That model is what sizes the PREPARE and STOP CROSS TRAFFIC
alerts. The jam forecast here supplies the "how bad will it be when the vehicle arrives" input to
it. The view, `CREATE MODEL`, evaluate and predict steps stay the same; only the label and
the join change.
