#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EWMA 기반 실시간 이상 탐지 패키지

기존 FastAPI 서버에 쉽게 통합할 수 있는 이상 탐지 패키지입니다.
기존 StreamingDetector를 래핑하여 간단한 API로 제공합니다.

사용법:
```python
from anomaly_detector_package import AnomalyDetectorManager
from fastapi import FastAPI

app = FastAPI()
detector_manager = AnomalyDetectorManager("ewma_baseline_ch01.json")

@app.post("/api/sensor-data")
async def process_sensor_data(data: dict):
    result = await detector_manager.process_data(data)
    return result
```

작성자: AI Assistant
버전: v1.0
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
import pandas as pd
from dataclasses import dataclass

# 기존 탐지 엔진 임포트
from home_env_power_detector_v3 import StreamingDetector, EWMABaseline, Config, Event

# =============================================================================
# 데이터 모델 및 결과 클래스
# =============================================================================

@dataclass
class SensorReading:
    """
    센서 데이터 읽기 클래스 (간단한 dict도 받을 수 있음)
    """
    power_W: float
    timestamp: Optional[str] = None
    temp_C: Optional[float] = None
    rh_pct: Optional[float] = None
    lux: Optional[float] = None
    outdoor_temp_C: Optional[float] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensorReading":
        """딕셔너리에서 SensorReading 객체 생성"""
        return cls(
            power_W=float(data.get("power_W", data.get("power", 0))),
            timestamp=data.get("timestamp"),
            temp_C=data.get("temp_C", data.get("temperature")),
            rh_pct=data.get("rh_pct", data.get("humidity")),
            lux=data.get("lux"),
            outdoor_temp_C=data.get("outdoor_temp_C", data.get("outside_temp"))
        )

@dataclass
class DetectionResult:
    """
    탐지 결과 클래스
    """
    timestamp: str
    is_anomaly: bool
    events: List[Dict[str, Any]]
    sensor_data: Dict[str, Any]
    stats: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "timestamp": self.timestamp,
            "is_anomaly": self.is_anomaly,
            "events": self.events,
            "sensor_data": self.sensor_data,
            "stats": self.stats
        }

# =============================================================================
# 메인 이상 탐지 매니저 클래스
# =============================================================================

class AnomalyDetectorManager:
    """
    EWMA 기반 실시간 이상 탐지 매니저
    
    기존 FastAPI 서버에 쉽게 통합할 수 있는 간단한 인터페이스 제공
    """
    
    def __init__(
        self, 
        baseline_file: str = "ewma_baseline_ch01.json",
        config: Optional[Config] = None,
        alert_callback: Optional[Callable[[DetectionResult], None]] = None,
        log_level: str = "INFO"
    ):
        """
        탐지 매니저 초기화
        
        Args:
            baseline_file: EWMA 베이스라인 JSON 파일 경로
            config: 탐지 설정 (None이면 기본값 사용)
            alert_callback: 이상 탐지 시 호출할 콜백 함수
            log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.log_level = log_level
        self._log("INFO", "🚀 이상 탐지 매니저 초기화 중...")
        
        try:
            # 베이스라인 로드
            self.baseline = EWMABaseline.from_json(baseline_file)
            self._log("INFO", f"✅ 베이스라인 로드: 평균={self.baseline.mean():.1f}W, 표준편차={self.baseline.std():.1f}W")
            
            # 설정 및 탐지기 초기화
            self.config = config or Config()
            self.detector = StreamingDetector(self.baseline, self.config)
            
            # 콜백 및 통계
            self.alert_callback = alert_callback
            self.total_processed = 0
            self.total_anomalies = 0
            self.start_time = datetime.now()
            
            self._log("INFO", f"🔍 탐지기 준비 완료 (EWMA_k={self.config.ewma_k}, 전류한계={self.config.current_limit_A}A)")
            
        except Exception as e:
            self._log("ERROR", f"❌ 초기화 실패: {e}")
            raise
    
    def _log(self, level: str, message: str):
        """간단한 로깅"""
        if self.log_level == "DEBUG" or (self.log_level == "INFO" and level in ["INFO", "WARNING", "ERROR"]) or (self.log_level == "WARNING" and level in ["WARNING", "ERROR"]) or (self.log_level == "ERROR" and level == "ERROR"):
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")
    
    async def process_data(self, data: Dict[str, Any]) -> DetectionResult:
        """
        센서 데이터를 처리하고 이상 탐지 수행
        
        Args:
            data: 센서 데이터 딕셔너리
                 필수: power_W (또는 power)
                 선택: timestamp, temp_C, rh_pct, lux, outdoor_temp_C
        
        Returns:
            DetectionResult: 탐지 결과
        """
        try:
            # 데이터 파싱
            sensor_reading = SensorReading.from_dict(data)
            
            # 타임스탬프 처리
            if sensor_reading.timestamp:
                try:
                    ts = pd.to_datetime(sensor_reading.timestamp)
                except:
                    ts = pd.Timestamp.now()
            else:
                ts = pd.Timestamp.now()
            
            # 이상 탐지 수행 (기존 StreamingDetector 사용)
            events = self.detector.update(
                ts=ts,
                power_W=sensor_reading.power_W,
                room_temp_C=sensor_reading.temp_C,
                room_rh_pct=sensor_reading.rh_pct,
                lux=sensor_reading.lux,
                outdoor_temp_C=sensor_reading.outdoor_temp_C
            )
            
            # 통계 업데이트
            self.total_processed += 1
            if events:
                self.total_anomalies += len(events)
            
            # 현재 탐지기 통계
            current_stats = self.detector._stats()
            
            # 결과 생성
            result = DetectionResult(
                timestamp=ts.isoformat(),
                is_anomaly=len(events) > 0,
                events=[{
                    "type": event.type,
                    "start": event.start.isoformat(),
                    "end": event.end.isoformat(),
                    "severity": event.severity,
                    "info": event.info
                } for event in events],
                sensor_data={
                    "power_W": sensor_reading.power_W,
                    "temp_C": sensor_reading.temp_C,
                    "rh_pct": sensor_reading.rh_pct,
                    "lux": sensor_reading.lux,
                    "outdoor_temp_C": sensor_reading.outdoor_temp_C
                },
                stats={
                    "current_mean_W": round(current_stats[0], 2),
                    "current_std_W": round(current_stats[1], 2),
                    "total_processed": self.total_processed,
                    "total_anomalies": self.total_anomalies,
                    "uptime_minutes": round((datetime.now() - self.start_time).total_seconds() / 60, 1)
                }
            )
            
            # 로깅
            if events:
                self._log("WARNING", f"🚨 이상 탐지! {len(events)}개 이벤트 (전력: {sensor_reading.power_W}W)")
                for event in events:
                    self._log("WARNING", f"   • {event.type} ({event.severity})")
            else:
                if self.total_processed % 10 == 0:  # 10개마다 로그
                    self._log("DEBUG", f"✅ 정상 - 전력: {sensor_reading.power_W}W (처리: {self.total_processed}개)")
            
            # 콜백 호출
            if events and self.alert_callback:
                try:
                    if asyncio.iscoroutinefunction(self.alert_callback):
                        await self.alert_callback(result)
                    else:
                        self.alert_callback(result)
                except Exception as e:
                    self._log("ERROR", f"❌ 콜백 오류: {e}")
            
            return result
            
        except Exception as e:
            self._log("ERROR", f"❌ 데이터 처리 오류: {e}")
            raise
    
    def process_data_sync(self, data: Dict[str, Any]) -> DetectionResult:
        """
        동기 버전의 데이터 처리 (비동기 환경이 아닐 때 사용)
        """
        return asyncio.run(self.process_data(data))
    
    def get_status(self) -> Dict[str, Any]:
        """
        현재 탐지기 상태 반환
        """
        current_stats = self.detector._stats()
        return {
            "status": "running",
            "uptime_minutes": round((datetime.now() - self.start_time).total_seconds() / 60, 1),
            "total_processed": self.total_processed,
            "total_anomalies": self.total_anomalies,
            "anomaly_rate": round(self.total_anomalies / max(1, self.total_processed) * 100, 2),
            "detector_stats": {
                "current_mean_W": round(current_stats[0], 2),
                "current_std_W": round(current_stats[1], 2)
            },
            "config": {
                "ewma_k": self.config.ewma_k,
                "current_limit_A": self.config.current_limit_A,
                "spike_delta_A": self.config.spike_delta_A
            }
        }
    
    def reset_stats(self):
        """통계 초기화"""
        self.total_processed = 0
        self.total_anomalies = 0
        self.start_time = datetime.now()
        self._log("INFO", "📊 통계 초기화됨")

# =============================================================================
# 편의 함수들
# =============================================================================

def create_detector_manager(
    baseline_file: str = "ewma_baseline_ch01.json",
    **kwargs
) -> AnomalyDetectorManager:
    """
    탐지 매니저 생성 편의 함수
    """
    return AnomalyDetectorManager(baseline_file, **kwargs)

async def quick_detect(data: Dict[str, Any], baseline_file: str = "ewma_baseline_ch01.json") -> DetectionResult:
    """
    빠른 일회성 탐지 (매번 새 인스턴스 생성)
    """
    manager = AnomalyDetectorManager(baseline_file, log_level="ERROR")
    return await manager.process_data(data)

# =============================================================================
# 사용 예시 및 테스트 코드
# =============================================================================

if __name__ == "__main__":
    """
    패키지 테스트 및 사용 예시
    """
    import asyncio
    
    async def alert_handler(result: DetectionResult):
        """이상 탐지 시 호출될 콜백"""
        print(f"🚨 ALERT! {len(result.events)}개 이상 이벤트 발생!")
        for event in result.events:
            print(f"   • {event['type']} ({event['severity']})")
    
    async def main():
        print("🧪 이상 탐지 패키지 테스트")
        print("=" * 50)
        
        # 매니저 생성
        manager = AnomalyDetectorManager(
            baseline_file="ewma_baseline_ch01.json",
            alert_callback=alert_handler,
            log_level="INFO"
        )
        
        # 테스트 데이터
        test_cases = [
            {"power_W": 1000, "temp_C": 25, "lux": 100},  # 정상
            {"power": 1050, "temperature": 26},            # 정상 (다른 키명)
            {"power_W": 8000, "temp_C": 25},               # 이상 (과전류)
            {"power_W": 500, "temp_C": 25},                # 이상 (급격한 변화)
        ]
        
        print("\n📊 테스트 시작...")
        for i, data in enumerate(test_cases, 1):
            print(f"\n[{i}] 데이터: {data}")
            result = await manager.process_data(data)
            
            status = "🚨 이상!" if result.is_anomaly else "✅ 정상"
            print(f"    결과: {status}")
            
            await asyncio.sleep(1)  # 1초 간격
        
        # 상태 확인
        print(f"\n📈 최종 상태:")
        status = manager.get_status()
        print(f"   처리된 데이터: {status['total_processed']}개")
        print(f"   탐지된 이상: {status['total_anomalies']}개")
        print(f"   이상 비율: {status['anomaly_rate']}%")
    
    # 테스트 실행
    asyncio.run(main())
