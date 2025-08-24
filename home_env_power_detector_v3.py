
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd, numpy as np, json
import math

def _ensure_dt_index(s: pd.Series) -> pd.Series:
    """
    pandas Series의 인덱스가 DatetimeIndex인지 확인하고 정리합니다.
    
    Args:
        s: 검사할 pandas Series
        
    Returns:
        중복 제거 및 정렬된 pandas Series
        
    Raises:
        ValueError: 인덱스가 DatetimeIndex가 아닌 경우
    """
    if not isinstance(s.index, pd.DatetimeIndex):
        raise ValueError("Series/DataFrame must use DatetimeIndex.")
    if s.index.has_duplicates:
        # 중복된 타임스탬프 제거 (첫 번째 값만 유지)
        s = s[~s.index.duplicated(keep="first")]
    return s.sort_index()

def _mad_scaled(x: np.ndarray) -> float:
    """
    중앙값 절대 편차(MAD)를 계산하고 정규분포 표준편차와 유사하게 스케일링합니다.
    
    이상치에 덜 민감한 분산 추정치로, 정규분포에서 MAD * 1.4826 ≈ 표준편차입니다.
    
    Args:
        x: 분석할 numpy 배열
        
    Returns:
        스케일링된 MAD 값 (표준편차 추정치)
    """
    med = np.median(x)  # 중앙값 계산
    mad = np.median(np.abs(x - med))  # 중앙값으로부터의 절대 편차의 중앙값
    return 1.4826 * mad  # 정규분포 가정 하에 표준편차와 동등하게 스케일링

def _nearest_join(left: pd.DataFrame, right: pd.DataFrame, on: str, tol_s: float) -> pd.DataFrame:
    """
    두 DataFrame을 시간 기준으로 가장 가까운 값으로 조인합니다.
    
    주로 시간 간격이 다른 센서 데이터를 통합할 때 사용됩니다.
    예: 2초 간격 전력 데이터 + 10분 간격 날씨 데이터
    
    Args:
        left: 기준이 되는 DataFrame (시간 인덱스)
        right: 조인할 DataFrame (시간 인덱스)
        on: 조인할 컬럼명
        tol_s: 허용 오차 (초 단위)
        
    Returns:
        left DataFrame에 right의 데이터가 조인된 결과
    """
    tol = pd.to_timedelta(tol_s, unit="s")  # 허용 오차를 timedelta로 변환
    r = right[[on]].copy()
    r = r[~r.index.duplicated(keep="first")].sort_index()  # 중복 제거 및 정렬
    # left의 각 시점에 대해 right에서 가장 가까운 시점의 값을 찾아 매칭
    matched = r.reindex(left.index, method="nearest", tolerance=tol)
    out = left.copy()
    out[on] = matched[on].values  # 매칭된 값을 left에 추가
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
        """
        누적된 통계로부터 평균을 계산합니다.
        
        Returns:
            전력 데이터의 평균값 (W)
        """
        return self.sum / max(1, self.n)  # 0으로 나누기 방지

    def std(self) -> float:
        """
        누적된 통계로부터 표준편차를 계산합니다.
        
        온라인 알고리즘을 사용하여 메모리 효율적으로 계산합니다.
        공식: σ = √(E[X²] - E[X]²)
        
        Returns:
            전력 데이터의 표준편차 (W)
        """
        mu = self.mean()
        # 분산 = E[X²] - E[X]² (음수 방지를 위해 max 사용)
        variance = max(0.0, self.sum_sqr / max(1, self.n) - mu*mu)
        return math.sqrt(variance)

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
        """
        새로운 전력 값으로 누적 통계를 업데이트합니다.
        
        온라인 알고리즘으로 메모리 효율적인 통계 계산을 수행합니다.
        
        Args:
            value_w: 새로운 전력 값 (W)
        """
        self._n += 1  # 데이터 포인트 개수 증가
        self._sum += value_w  # 합계 업데이트
        self._sum_sqr += value_w * value_w  # 제곱합 업데이트

    def _stats(self) -> Tuple[float,float]:
        """
        현재 누적 통계로부터 평균과 표준편차를 계산합니다.
        
        Returns:
            (평균, 표준편차) 튜플 (단위: W)
        """
        mu = self._sum / max(1, self._n)  # 평균 계산
        # 분산 계산 (음수 방지)
        var = max(0.0, self._sum_sqr / max(1, self._n) - mu*mu)
        return mu, math.sqrt(var)  # (평균, 표준편차) 반환

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

# 중복 코드 제거 - 위에 이미 정의된 함수들과 import 구문이므로 삭제

@dataclass
class EWMABaseline:
    """
    EWMA(지수 가중 이동 평균) 베이스라인 통계를 저장하는 데이터 클래스.
    n: 데이터 포인트 수
    sum: 값들의 합계
    sum_sqr: 값들의 제곱 합계
    """
    n: int
    sum: float
    sum_sqr: float

    @classmethod
    def from_json(cls, path: str) -> "EWMABaseline":
        """
        JSON 파일로부터 EWMABaseline 객체를 로드합니다.
        """
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls(n=int(d["n"]), sum=float(d["sum"]), sum_sqr=float(d["sum_sqr"]))

    def mean(self) -> float:
        """
        현재 통계를 기반으로 평균을 계산합니다.
        """
        return self.sum / max(1, self.n)

    def std(self) -> float:
        """
        현재 통계를 기반으로 표준 편차를 계산합니다.
        """
        mu = self.mean()
        return math.sqrt(max(0.0, self.sum_sqr / max(1, self.n) - mu*mu))

@dataclass
class Config:
    """
    이상 탐지 모델의 모든 설정 파라미터를 정의하는 데이터 클래스.
    각 파라미터는 탐지 로직의 민감도와 기준을 제어합니다.
    """
    ewma_alpha: float = 0.2 # EWMA 가중치 (최신 데이터에 대한 민감도)
    ewma_k: float = 3.0 # EWMA Z-스코어 임계값 (이 값을 초과하면 이상으로 간주)
    ewma_sustain_sec: float = 10.0 # EWMA 이상 상태가 지속되어야 하는 최소 시간 (초)
    mains_voltage_V: float = 220.0 # 주 전압 (볼트)
    current_limit_A: float = 30.0 # 전류 제한 (암페어)
    near_limit_ratio: float = 0.9 # 전류 제한에 근접했다고 판단하는 비율
    near_limit_min_sec: float = 4.0 # 전류 제한 근접 상태가 지속되어야 하는 최소 시간 (초)
    spike_delta_A: float = 10.0 # 전류 스파이크로 간주하는 최소 변화량 (암페어)
    spike_abs_A: float = 40.0 # 전류 스파이크로 간주하는 절대 임계값 (암페어)
    spike_quiet_sec: float = 4.0 # 스파이크 탐지 후 다음 스파이크 탐지까지의 대기 시간 (초)
    summer_months: tuple = (6,7,8) # 여름으로 간주하는 월
    winter_months: tuple = (12,1,2) # 겨울로 간주하는 월
    summer_indoor_over_outdoor_warn: float = 1.0 # 여름철 실내 온도가 실외보다 높을 때 경고 임계값
    summer_indoor_over_outdoor_alert: float = 3.0 # 여름철 실내 온도가 실외보다 높을 때 알림 임계값
    winter_indoor_above_outdoor_min_warn: float = 5.0 # 겨울철 실내 온도가 실외보다 낮을 때 경고 임계값 (차이가 이 값 이하)
    winter_indoor_above_outdoor_min_alert: float = 3.0 # 겨울철 실내 온도가 실외보다 낮을 때 알림 임계값 (차이가 이 값 이하)
    use_lux_gate: bool = True # 조도 센서를 사용하여 재실 여부를 판단할지 여부
    occupancy_lux_threshold: float = 20.0 # 재실로 판단하는 최소 조도 (lux)

@dataclass
class Event:
    """
    탐지된 이상 징후 이벤트를 나타내는 데이터 클래스.
    type: 이벤트 유형 (예: "power_ewma_anomaly", "overcurrent_near_limit")
    start: 이벤트 시작 타임스탬프
    end: 이벤트 종료 타임스탬프
    severity: 이벤트 심각도 ("warn" 또는 "alert")
    info: 이벤트에 대한 추가 정보 (딕셔너리)
    """
    type: str
    start: pd.Timestamp
    end: pd.Timestamp
    severity: str
    info: Dict[str, Any]

class StreamingDetector:
    """
    스트리밍 데이터를 실시간으로 처리하며 이상 징후를 탐지하는 클래스.
    EWMA, 전류 기반, 온도 기반 탐지 로직을 포함합니다.
    """
    def __init__(self, baseline: EWMABaseline, cfg: Optional[Config] = None, sample_period_s: float = 2.0):
        """
        탐지기 초기화.
        baseline: 초기 통계 정보를 제공하는 EWMABaseline 객체.
        cfg: 탐지 설정을 포함하는 Config 객체. 제공되지 않으면 기본 Config 사용.
        sample_period_s: 데이터 샘플링 주기 (초).
        """
        self.baseline = baseline
        self.cfg = cfg or Config() # 설정 객체 초기화
        self.dt = float(sample_period_s) # 샘플링 주기
        self._ewma = 0.0 # EWMA 값
        self._ewma_breaching = False # EWMA 임계값 위반 중인지 여부
        self._ewma_start = None # EWMA 임계값 위반 시작 시간
        self._ewma_peak = 0.0 # EWMA 임계값 위반 중 최대 Z-스코어
        self._over_start = None # 과전류/제한 근접 시작 시간
        self._over_active = False # 과전류/제한 근접 상태 활성 여부
        self._last_I = None # 이전 전류 값 (스파이크 탐지용)
        self._last_ts = None # 이전 타임스탬프 (스파이크 탐지용)
        # 베이스라인 통계 초기화
        self._n = baseline.n
        self._sum = baseline.sum
        self._sum_sqr = baseline.sum_sqr

    def _lux_ok(self, lux: Optional[float]) -> bool:
        """
        조도(lux) 값을 기반으로 재실 여부를 판단합니다.
        Config에서 use_lux_gate가 True이고 lux 값이 임계값 이상일 때 True를 반환합니다.
        """
        if not self.cfg.use_lux_gate:
            return True # 조도 게이트를 사용하지 않으면 항상 True
        # lux 값이 존재하고 임계값 이상일 때만 True
        return (lux is not None) and (lux >= self.cfg.occupancy_lux_threshold)

    def _update_stats(self, value_w: float):
        """
        EWMA 베이스라인 통계(n, sum, sum_sqr)를 업데이트합니다.
        """
        self._n += 1
        self._sum += value_w
        self._sum_sqr += value_w * value_w

    def _stats(self) -> Tuple[float,float]:
        """
        현재 통계를 기반으로 평균과 표준 편차를 계산하여 반환합니다.
        """
        mu = self._sum / max(1, self._n)
        var = max(0.0, self._sum_sqr / max(1, self._n) - mu*mu)
        return mu, math.sqrt(var)

    def update(self, ts: pd.Timestamp, power_W: float,
               room_temp_C: Optional[float] = None,
               room_rh_pct: Optional[float] = None,
               lux: Optional[float] = None,
               outdoor_temp_C: Optional[float] = None) -> List[Event]:
        """
        새로운 데이터 포인트(타임스탬프, 전력, 선택적 환경 데이터)를 처리하고
        탐지된 이상 징후 이벤트 목록을 반환합니다.
        """
        out: List[Event] = []

        # 1. 전력 EWMA 기반 이상 탐지
        self._update_stats(power_W) # 통계 업데이트
        mu, sd = self._stats() # 현재 평균 및 표준 편차
        alpha = self.cfg.ewma_alpha
        self._ewma = alpha * power_W + (1 - alpha) * self._ewma # EWMA 값 계산
        z = 0.0 if sd == 0.0 else (power_W - self._ewma) / sd # Z-스코어 계산
        above = abs(z) > self.cfg.ewma_k # Z-스코어가 임계값을 초과하는지 확인

        if above and not self._ewma_breaching:
            # EWMA 임계값 위반 시작
            self._ewma_breaching = True
            self._ewma_start = ts
            self._ewma_peak = abs(z)
        elif above and self._ewma_breaching:
            # EWMA 임계값 위반 지속 중, 최대 Z-스코어 업데이트
            self._ewma_peak = max(self._ewma_peak, abs(z))
        elif (not above) and self._ewma_breaching:
            # EWMA 임계값 위반 종료
            duration = (ts - self._ewma_start).total_seconds()
            if duration >= self.cfg.ewma_sustain_sec:
                # 위반 지속 시간이 설정된 임계값 이상이면 이벤트 발생
                out.append(Event(
                    type="power_ewma_anomaly",
                    start=self._ewma_start, end=ts, severity="alert",
                    info={"z_peak": float(self._ewma_peak), "mu_W": float(mu), "sd_W": float(sd)}
                ))
            self._ewma_breaching = False
            self._ewma_start = None
            self._ewma_peak = 0.0

        # 2. 전류 기반 이상 탐지 (과전류 및 스파이크)
        V = self.cfg.mains_voltage_V
        I = power_W / max(1e-9, V) # 전력(W)을 전류(A)로 변환 (I = P/V)

        warn_level = self.cfg.near_limit_ratio * self.cfg.current_limit_A # 경고 수준 전류 계산
        if I >= warn_level:
            # 전류가 경고 수준 이상일 때
            if not self._over_active:
                # 과전류 상태 시작
                self._over_active = True
                self._over_start = ts
            else:
                # 과전류 상태 지속 중
                duration = (ts - self._over_start).total_seconds()
                if duration >= self.cfg.near_limit_min_sec:
                    # 지속 시간이 임계값 이상이면 이벤트 발생
                    sev = "alert" if I >= self.cfg.current_limit_A else "warn" # 실제 제한 초과 여부에 따라 심각도 결정
                    out.append(Event(
                        type="overcurrent_near_limit",
                        start=self._over_start, end=ts, severity=sev,
                        info={"I_A": float(I), "limit_A": float(self.cfg.current_limit_A),
                              "ratio": float(I / self.cfg.current_limit_A)}
                    ))
                    self._over_start = ts # 이벤트 발생 후 시작 시간 업데이트 (연속 이벤트 처리)
        else:
            # 전류가 경고 수준 미만으로 내려감
            self._over_active = False
            self._over_start = None

        if self._last_I is not None and self._last_ts is not None:
            # 이전 전류 값과 비교하여 스파이크 탐지
            dI = I - self._last_I # 전류 변화량
            if (abs(dI) >= self.cfg.spike_delta_A) or (I >= self.cfg.spike_abs_A):
                # 전류 변화량이 임계값 이상이거나 절대 전류값이 스파이크 임계값 이상일 때
                out.append(Event(
                    type="short_spike_suspect",
                    start=self._last_ts, end=ts, severity="alert",
                    info={"delta_A": float(dI), "I_A": float(I)}
                ))
        self._last_I = I # 현재 전류 값을 다음 비교를 위해 저장
        self._last_ts = ts # 현재 타임스탬프를 다음 비교를 위해 저장

        # 3. 온도 기반 이상 탐지 (실내 vs 실외)
        # 실내 온도, 실외 온도, 조도 데이터가 모두 유효하고 재실로 판단될 때만 실행
        if (room_temp_C is not None) and (outdoor_temp_C is not None) and self._lux_ok(lux):
            m = ts.month # 현재 월
            if m in self.cfg.summer_months:
                # 여름철 로직: 실내 온도가 실외보다 비정상적으로 높을 때
                diff = room_temp_C - outdoor_temp_C
                if diff >= self.cfg.summer_indoor_over_outdoor_alert:
                    out.append(Event("thermal_summer_room_hot_vs_outdoor", ts, ts, "alert",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
                elif diff >= self.cfg.summer_indoor_over_outdoor_warn:
                    out.append(Event("thermal_summer_room_hot_vs_outdoor", ts, ts, "warn",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
            if m in self.cfg.winter_months:
                # 겨울철 로직: 실내 온도가 실외보다 충분히 따뜻하지 않을 때
                diff = room_temp_C - outdoor_temp_C
                if diff <= self.cfg.winter_indoor_above_outdoor_min_alert:
                    out.append(Event("thermal_winter_room_too_cold_vs_outdoor", ts, ts, "alert",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
                elif diff <= self.cfg.winter_indoor_above_outdoor_min_warn:
                    out.append(Event("thermal_winter_room_too_cold_vs_outdoor", ts, ts, "warn",
                                     {"room_C": float(room_temp_C), "outdoor_C": float(outdoor_temp_C), "delta_C": float(diff)}))
        return out # 탐지된 이벤트 목록 반환

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
    """
    배치 모드로 이상 탐지를 실행하는 메인 함수.
    CSV 파일로부터 데이터를 읽어와 StreamingDetector를 사용하여 이상 징후를 탐지합니다.

    input_csv: 전력 및 환경 센서 데이터가 포함된 입력 CSV 파일 경로.
    baseline_json: EWMA 베이스라인 통계가 저장된 JSON 파일 경로.
    weather_csv: (선택 사항) 외부 온도 데이터가 포함된 CSV 파일 경로.
    tz: (선택 사항) 타임스탬프에 적용할 시간대 (예: "Asia/Seoul").
    cfg: (선택 사항) 탐지 설정을 포함하는 Config 객체.
    sample_period_s: 데이터 샘플링 주기 (초).
    out_csv: (선택 사항) 탐지된 이벤트를 저장할 출력 CSV 파일 경로.
    weather_col_candidates: weather_csv에서 외부 온도 컬럼을 찾을 때 사용할 후보 컬럼명 튜플.
    """
    cfg = cfg or Config() # 설정 객체 초기화

    # 1. 입력 CSV 파일 로드 및 전처리
    print(f"📁 입력 파일 로드 중: {input_csv}")
    df = pd.read_csv(input_csv)
    print(f"✅ 데이터 로드 완료: {len(df)}개 행, {len(df.columns)}개 컬럼")
    
    # 타임스탬프 컬럼 찾기 및 DatetimeIndex로 설정
    # 다양한 타임스탬프 컬럼명을 지원 (timestamp, time, ts, datetime)
    ts_col = [c for c in df.columns if str(c).lower() in ("timestamp","time","ts","datetime")]
    if not ts_col:
        raise ValueError("input_csv must contain a 'timestamp' column")
    ts_col = ts_col[0]
    print(f"🕐 타임스탬프 컬럼 발견: '{ts_col}'")
    
    df[ts_col] = pd.to_datetime(df[ts_col]) # datetime 객체로 변환
    if tz:
        # 시간대 설정 (DST 및 존재하지 않는 시간 처리 포함)
        df[ts_col] = df[ts_col].dt.tz_localize(tz, ambiguous='NaT', nonexistent='shift_forward')
        print(f"🌍 시간대 설정: {tz}")
    
    df = df.set_index(ts_col).sort_index() # 인덱스를 타임스탬프로 설정하고 시간순 정렬
    print(f"📊 데이터 기간: {df.index.min()} ~ {df.index.max()}")

    # 전력 컬럼 찾기 (다양한 명명 규칙 지원)
    p_cols = [c for c in df.columns if str(c).lower() in ("power_w","power","watts","w")]
    if not p_cols:
        raise ValueError("input_csv must contain a power column (power_W/power/watts/w)")
    p_col = p_cols[0]
    print(f"⚡ 전력 컬럼 발견: '{p_col}' (범위: {df[p_col].min():.1f}W ~ {df[p_col].max():.1f}W)")

    # 선택적 환경 센서 컬럼명 표준화
    # 다양한 센서 데이터 포맷을 통일된 컬럼명으로 변환
    col_map = {}
    sensor_mapping = [
        ("temp_c", "room_temp_C", "실내온도"),
        ("room_temp_c", "room_temp_C", "실내온도"), 
        ("rh", "rh_pct", "상대습도"),
        ("humidity", "rh_pct", "상대습도"),
        ("lux", "lux", "조도")
    ]
    
    found_sensors = []
    for cand, name, desc in sensor_mapping:
        for c in df.columns:
            if str(c).lower() == cand:
                col_map[c] = name
                found_sensors.append(f"{desc}({c})")
    
    df = df.rename(columns=col_map)
    if found_sensors:
        print(f"🌡️  환경 센서 발견: {', '.join(found_sensors)}")
    else:
        print("⚠️  환경 센서 데이터 없음 (전력 기반 탐지만 수행)")

    # 2. 외부 날씨 CSV 파일 로드 및 조인 (선택 사항)
    # 온도 기반 이상 탐지를 위한 실외 온도 데이터 통합
    if weather_csv:
        print(f"🌤️  외부 날씨 데이터 로드 중: {weather_csv}")
        w = pd.read_csv(weather_csv)
        
        # 날씨 데이터의 타임스탬프 컬럼 찾기 및 DatetimeIndex로 설정
        w_ts_col = [c for c in w.columns if str(c).lower() in ("timestamp","time","ts","datetime")]
        if not w_ts_col:
            raise ValueError("weather_csv must have a timestamp column")
        w_ts_col = w_ts_col[0]
        w[w_ts_col] = pd.to_datetime(w[w_ts_col])
        if tz:
            w[w_ts_col] = w[w_ts_col].dt.tz_localize(tz, ambiguous='NaT', nonexistent='shift_forward')
        w = w.set_index(w_ts_col).sort_index()
        
        # 외부 온도 컬럼 찾기 (다양한 컬럼명 지원)
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
        
        # 메인 데이터프레임에 외부 온도 데이터 시간 기준 조인
        # 600초(10분) 허용 오차로 가장 가까운 시간의 날씨 데이터를 매칭
        before_join = len(df)
        df = _nearest_join(df, w[[w_temp_col]].rename(columns={w_temp_col: "outside_temp_C"}),
                           on="outside_temp_C", tol_s=600)
        matched_count = df['outside_temp_C'].notna().sum()
        print(f"🔗 날씨 데이터 조인 완료: {matched_count}/{before_join}개 시점 매칭")
    else:
        print("🌡️  외부 날씨 데이터 없음 (온도 기반 탐지 비활성화)")

    # 3. 이상 탐지 엔진 초기화
    print(f"🧠 베이스라인 모델 로드 중: {baseline_json}")
    base = EWMABaseline.from_json(baseline_json) # 사전 학습된 통계 베이스라인 로드
    print(f"📈 베이스라인 통계: 평균={base.mean():.1f}W, 표준편차={base.std():.1f}W (학습 데이터: {base.n:,}개)")
    
    # 스트리밍 탐지기 인스턴스 생성
    det = StreamingDetector(base, cfg=cfg, sample_period_s=sample_period_s)
    print(f"🔍 탐지기 초기화 완료 (샘플링 주기: {sample_period_s}초)")
    print(f"⚙️  탐지 설정: EWMA_k={cfg.ewma_k}, 전류한계={cfg.current_limit_A}A, 스파이크임계={cfg.spike_delta_A}A")

    # 4. 실시간 스트리밍 이상 탐지 수행
    print(f"🚀 이상 탐지 시작... (처리 대상: {len(df):,}개 데이터 포인트)")
    
    rows = []  # 탐지된 이벤트를 저장할 리스트
    processed_count = 0
    
    # 데이터프레임의 각 시점을 순회하며 실시간 탐지 시뮬레이션
    for ts, row in df.iterrows():
        # StreamingDetector에 새로운 데이터 포인트 입력
        evs = det.update(
            ts = ts,  # 현재 타임스탬프
            power_W = float(row[p_col]),  # 전력 데이터 (필수)
            # 선택적 환경 센서 데이터 (없거나 NaN이면 None으로 전달)
            room_temp_C = float(row["room_temp_C"]) if "room_temp_C" in row and not pd.isna(row["room_temp_C"]) else None,
            room_rh_pct = float(row["rh_pct"]) if "rh_pct" in row and not pd.isna(row["rh_pct"]) else None,
            lux = float(row["lux"]) if "lux" in row and not pd.isna(row["lux"]) else None,
            outdoor_temp_C = float(row["outside_temp_C"]) if "outside_temp_C" in row and not pd.isna(row["outside_temp_C"]) else None,
        )
        
        # 탐지된 이벤트들을 결과 목록에 추가
        for e in evs:
            rows.append(dict(
                type=e.type,  # 이벤트 유형
                start=e.start,  # 시작 시간
                end=e.end,  # 종료 시간
                severity=e.severity,  # 심각도 (warn/alert)
                info_json=json.dumps(e.info, ensure_ascii=False)  # 상세 정보 (JSON)
            ))
            print(f"🚨 이상 탐지: {e.type} ({e.severity}) at {e.start}")
        
        processed_count += 1
        # 진행 상황 출력 (매 10000개마다)
        if processed_count % 10000 == 0:
            print(f"📊 진행률: {processed_count:,}/{len(df):,} ({100*processed_count/len(df):.1f}%)")
    
    # 탐지 결과를 DataFrame으로 변환
    out_df = pd.DataFrame(rows)
    print(f"✅ 탐지 완료! 총 {len(out_df)}개의 이상 이벤트 발견")

    # 5. 결과 저장 및 요약
    if out_csv:
        out_df.to_csv(out_csv, index=False)
        print(f"💾 결과 저장 완료: {out_csv}")
    
    # 탐지 결과 요약 출력
    if not out_df.empty:
        print("\n📋 탐지 결과 요약:")
        summary = out_df.groupby(['type', 'severity']).size().reset_index(name='count')
        for _, row in summary.iterrows():
            print(f"   • {row['type']} ({row['severity']}): {row['count']}건")
    else:
        print("✨ 이상 징후가 발견되지 않았습니다.")
    
    return out_df  # 탐지된 이벤트 DataFrame 반환

    # 함수 종료 - 위에서 모든 로직이 완료됨
