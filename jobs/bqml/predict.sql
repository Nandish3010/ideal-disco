-- Next four 15-minute buckets per junction/approach, from each series' latest observed row.
-- Current jam_m, slow_m and ETA are held at their last values; only the clock features move.
WITH latest AS (
  SELECT * EXCEPT (rn) FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY junction_id, approach ORDER BY ts DESC) AS rn
    FROM corridor.traffic_features) WHERE rn = 1),
buckets AS (
  SELECT TIMESTAMP_ADD(TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MINUTE), INTERVAL 15 * k MINUTE) AS bucket_ts
  FROM UNNEST(GENERATE_ARRAY(1, 4)) AS k)
SELECT junction_id, approach, bucket_ts, predicted_next_jam_m
FROM ML.PREDICT(MODEL corridor.jam_forecast, (
  SELECT l.junction_id, l.approach, l.corridor, l.jam_m, l.slow_m, l.routes_eta_s, b.bucket_ts,
    EXTRACT(HOUR FROM b.bucket_ts AT TIME ZONE 'Asia/Kolkata') AS hour_of_day,
    EXTRACT(DAYOFWEEK FROM b.bucket_ts AT TIME ZONE 'Asia/Kolkata') AS day_of_week,
    EXTRACT(MINUTE FROM b.bucket_ts AT TIME ZONE 'Asia/Kolkata') AS minute_of_hour
  FROM latest l CROSS JOIN buckets b))
ORDER BY junction_id, approach, bucket_ts;
