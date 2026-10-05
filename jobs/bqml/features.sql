-- Features and next-step label for the jam forecast. Times are Asia/Kolkata.
CREATE OR REPLACE VIEW corridor.traffic_features AS
SELECT
  EXTRACT(HOUR FROM ts AT TIME ZONE 'Asia/Kolkata') AS hour_of_day,
  EXTRACT(DAYOFWEEK FROM ts AT TIME ZONE 'Asia/Kolkata') AS day_of_week,
  EXTRACT(MINUTE FROM ts AT TIME ZONE 'Asia/Kolkata') AS minute_of_hour,
  junction_id, approach, corridor, jam_m, slow_m, routes_eta_s,
  LEAD(jam_m) OVER (PARTITION BY junction_id, approach ORDER BY ts) AS next_jam_m,
  ts
FROM corridor.traffic_spans;
