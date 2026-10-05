-- Boosted trees, 20 rounds. The last row of each series has no label and is dropped.
CREATE OR REPLACE MODEL corridor.jam_forecast
OPTIONS (model_type = 'BOOSTED_TREE_REGRESSOR', input_label_cols = ['next_jam_m'], max_iterations = 20) AS
SELECT * EXCEPT (ts) FROM corridor.traffic_features
WHERE next_jam_m IS NOT NULL;
