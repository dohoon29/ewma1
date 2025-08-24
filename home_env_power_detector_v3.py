
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd, numpy as np, json
import math

def _ensure_dt_index(s: pd.Series) -> pd.Series:
    if not isinstance(s.index, pd.DatetimeIndex):
        raise ValueError("Series/DataFrame must use DatetimeIndex.")
    if s.index.has_duplicates:
        s = s[~s.index.duplicated(keep="first")]
    return s.sort_index()

def _mad_scaled(x: np.ndarray) -> float:
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    return 1.4826 * mad

def _nearest_join(left: pd.DataFrame, right: pd.DataFrame, on: str, tol_s: float) -> pd.DataFrame:
    tol = pd.to_timedelta(tol_s, unit="s")
    r = right[[on]].copy()
    r = r[~r.index.duplicated(keep="first")].sort_index()
    matched = r.reindex(left.index, method="nearest", tolerance=tol)
    out = left.copy()
    out[on] = matched[on].values
    return out

@dataclass
class EWMABaseline:
    n: int
    sum: float
    sum_sqr: float

    @classmethod
    def from_json(cls, path: str) -> "EWMABaseline":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls(n=int(d["n"]), sum=float(d["sum"]), sum_sqr=float(d["sum_sqr"]))

    def mean(self) -> float:
        return self.sum / max(1, self.n)

    def std(self) -> float:
        mu = self.mean()
        return math.sqrt(max(0.0, self.sum_sqr / max(1, self.n) - mu*mu))

@dataclass
class Config:
    ewma_alpha: float = 0.2
    ewma_k: float = 3.0
    ewma_sustain_sec: float = 10.0
    mains_voltage_V: float = 220.0
    current_limit_A: float = 30.0
    near_limit_ratio: float = 0.9
    near_limit_min_sec: float = 4.0
    spike_delta_A: float = 10.0
    spike_abs_A: float = 40.0
    spike_quiet_sec: float = 4.0
    summer_months: tuple = (6,7,8)
    winter_months: tuple = (12,1,2)
    summer_indoor_over_outdoor_warn: float = 1.0
    summer_indoor_over_outdoor_alert: float = 3.0
    winter_indoor_above_outdoor_min_warn: float = 5.0
    winter_indoor_above_outdoor_min_alert: float = 3.0
    use_lux_gate: bool = True
    occupancy_lux_threshold: float = 20.0

@dataclass
class Event:
    type: str
    start: pd.Timestamp
    end: pd.Timestamp
    severity: str
    info: Dict[str, Any]

class StreamingDetector:
    def __init__(self, baseline: EWMABaseline, cfg: Optional[Config] = None, sample_period_s: float = 2.0):
        self.baseline = baseline
        self.cfg = cfg or Config()
        self.dt = float(sample_period_s)
        self._ewma = 0.0
        self._ewma_breaching = False
        self._ewma_start = None
        self._ewma_peak = 0.0
        self._over_start = None
        self._over_active = False
        self._last_I = None
        self._last_ts = None
        self._n = baseline.n
        self._sum = baseline.sum
        self._sum_sqr = baseline.sum_sqr

    def _lux_ok(self, lux: Optional[float]) -> bool:
        if not self.cfg.use_lux_gate:
            return True
        return (lux is not None) and (lux >= self.cfg.occupancy_lux_threshold)

    def _update_stats(self, value_w: float):
        self._n += 1
        self._sum += value_w
        self._sum_sqr += value_w * value_w

    def _stats(self) -> Tuple[float,float]:
        mu = self._sum / max(1, self._n)
        var = max(0.0, self._sum_sqr / max(1, self._n) - mu*mu)
        return mu, math.sqrt(var)

    def update(self, ts: pd.Timestamp, power_W: float,
               room_temp_C: Optional[float] = None,
               room_rh_pct: Optional[float] = None,
               lux: Optional[float] = None,
               outdoor_temp_C: Optional[float] = None) -> List[Event]:
        out: List[Event] = []

        # EWMA on power_W
        self._update_stats(power_W)
        mu, sd = self._stats()
        alpha = self.cfg.ewma_alpha
        self._ewma = alpha * power_W + (1 - alpha) * self._ewma
        z = 0.0 if sd == 0.0 else (power_W - self._ewma) / sd
        above = abs(z) > self.cfg.ewma_k

        if above and not self._ewma_breaching:
            self._ewma_breaching = True
            self._ewma_start = ts
            self._ewma_peak = abs(z)
        elif above and self._ewma_breaching:
            self._ewma_peak = max(self._ewma_peak, abs(z))
        elif (not above) and self._ewma_breaching:
            duration = (ts - self._ewma_start).total_seconds()
            if duration >= self.cfg.ewma_sustain_sec:
                out.append(Event(
                    type="power_ewma_anomaly",
                    start=self._ewma_start, end=ts, severity="alert",
                    info={"z_peak": float(self._ewma_peak), "mu_W": float(mu), "sd_W": float(sd)}
                ))
            self._ewma_breaching = False
            self._ewma_start = None
            self._ewma_peak = 0.0

        # Electrical in Amps (power / V)
        V = self.cfg.mains_voltage_V
        I = power_W / max(1e-9, V)

        warn_level = self.cfg.near_limit_ratio * self.cfg.current_limit_A
        if I >= warn_level:
            if not self._over_active:
                self._over_active = True
                self._over_start = ts
            else:
                duration = (ts - self._over_start).total_seconds()
                if duration >= self.cfg.near_limit_min_sec:
                    sev = "alert" if I >= self.cfg.current_limit_A else "warn"
                    out.append(Event(
                        type="overcurrent_near_limit",
                        start=self._over_start, end=ts, severity=sev,
                        info={"I_A": float(I), "limit_A": float(self.cfg.current_limit_A),
                              "ratio": float(I / self.cfg.current_limit_A)}
                    ))
                    self._over_start = ts
        else:
            self._over_active = False
            self._over_start = None

        if self._last_I is not None and self._last_ts is not None:
            dI = I - self._last_I
            if (abs(dI) >= self.cfg.spike_delta_A) or (I >= self.cfg.spike_abs_A):
                out.append(Event(
                    type="short_spike_suspect",
                    start=self._last_ts, end=ts, severity="alert",
                    info={"delta_A": float(dI), "I_A": float(I)}
                ))
        self._last_I = I
        self._last_ts = ts

        # Thermal vs outdoor
        if (room_temp_C is not None) and (outdoor_temp_C is not None) and self._lux_ok(lux):
            m = ts.month
            if m in self.cfg.summer_months:
                diff = room_temp_C - outdoor_temp_C
                if diff >= self.cfg.summer_indoor_over_outdoor_alert:
                    out.append(Event("thermal_summer_room_hot_vs_outdoor", ts, ts, "alert",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
                elif diff >= self.cfg.summer_indoor_over_outdoor_warn:
                    out.append(Event("thermal_summer_room_hot_vs_outdoor", ts, ts, "warn",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
            if m in self.cfg.winter_months:
                diff = room_temp_C - outdoor_temp_C
                if diff <= self.cfg.winter_indoor_above_outdoor_min_alert:
                    out.append(Event("thermal_winter_room_too_cold_vs_outdoor", ts, ts, "alert",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
                elif diff <= self.cfg.winter_indoor_above_outdoor_min_warn:
                    out.append(Event("thermal_winter_room_too_cold_vs_outdoor", ts, ts, "warn",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
        return out

def run_batch(
    input_csv: str,
    baseline_json: str,
    weather_csv: Optional[str] = None,
    tz: Optional[str] = None,
    cfg: Optional[Config] = None,
    sample_period_s: float = 2.0,
    out_csv: Optional[str] = None,
    weather_col_candidates: tuple = ("outside_temp_C","outdoor_temp_C","temp_out_C"),
) -> pd.DataFrame:
    cfg = cfg or Config()

    df = pd.read_csv(input_csv)
    # timestamps
    ts_col = [c for c in df.columns if str(c).lower() in ("timestamp","time","ts","datetime")]
    if not ts_col:
        raise ValueError("input_csv must contain a 'timestamp' column")
    ts_col = ts_col[0]
    df[ts_col] = pd.to_datetime(df[ts_col])
    if tz:
        df[ts_col] = df[ts_col].dt.tz_localize(tz, ambiguous='NaT', nonexistent='shift_forward')
    df = df.set_index(ts_col).sort_index()

    # power column
    p_cols = [c for c in df.columns if str(c).lower() in ("power_w","power","watts","w")]
    if not p_cols:
        raise ValueError("input_csv must contain a power column (power_W/power/watts/w)")
    p_col = p_cols[0]

    # rename optional columns
    col_map = {}
    for cand, name in [("temp_c","room_temp_C"), ("room_temp_c","room_temp_C"),
                       ("rh","rh_pct"), ("humidity","rh_pct"),
                       ("lux","lux")]:
        for c in df.columns:
            if str(c).lower() == cand:
                col_map[c] = name
    df = df.rename(columns=col_map)

    # weather
    if weather_csv:
        w = pd.read_csv(weather_csv)
        w_ts_col = [c for c in w.columns if str(c).lower() in ("timestamp","time","ts","datetime")]
        if not w_ts_col:
            raise ValueError("weather_csv must have a timestamp column")
        w_ts_col = w_ts_col[0]
        w[w_ts_col] = pd.to_datetime(w[w_ts_col])
        if tz:
            w[w_ts_col] = w[w_ts_col].dt.tz_localize(tz, ambiguous='NaT', nonexistent='shift_forward')
        w = w.set_index(w_ts_col).sort_index()
        # pick temperature column
        w_temp_col = None
        for cand in weather_col_candidates:
            for c in w.columns:
                if str(c).lower() == cand.lower():
                    w_temp_col = c
                    break
            if w_temp_col:
                break
        if w_temp_col is None:
            raise ValueError(f"weather_csv must contain one of {weather_col_candidates}")
        df = _nearest_join(df, w[[w_temp_col]].rename(columns={w_temp_col: "outside_temp_C"}),
                           on="outside_temp_C", tol_s=600)

    base = EWMABaseline.from_json(baseline_json)
    det = StreamingDetector(base, cfg=cfg, sample_period_s=sample_period_s)

    rows = []
    for ts, row in df.iterrows():
        evs = det.update(
            ts = ts,
            power_W = float(row[p_col]),
            room_temp_C = float(row["room_temp_C"]) if "room_temp_C" in row and not pd.isna(row["room_temp_C"]) else None,
            room_rh_pct = float(row["rh_pct"]) if "rh_pct" in row and not pd.isna(row["rh_pct"]) else None,
            lux = float(row["lux"]) if "lux" in row and not pd.isna(row["lux"]) else None,
            outdoor_temp_C = float(row["outside_temp_C"]) if "outside_temp_C" in row and not pd.isna(row["outside_temp_C"]) else None,
        )
        for e in evs:
            rows.append(dict(type=e.type, start=e.start, end=e.end,
                             severity=e.severity, info_json=json.dumps(e.info, ensure_ascii=False)))
    out_df = pd.DataFrame(rows)
    if out_csv:
        out_df.to_csv(out_csv, index=False)
    return out_df
