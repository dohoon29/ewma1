#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
기존 FastAPI 서버에 이상 탐지 패키지 통합 예시

이 파일은 기존 FastAPI 서버에 이상 탐지 기능을 추가하는 방법을 보여줍니다.
실제 서버에서는 이 코드를 참고하여 기존 엔드포인트에 통합하세요.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
import asyncio
from datetime import datetime

# 우리가 만든 이상 탐지 패키지 임포트
from anomaly_detector_package import AnomalyDetectorManager, DetectionResult

# =============================================================================
# FastAPI 앱 및 데이터 모델
# =============================================================================

app = FastAPI(
    title="기존 서버 + 이상 탐지 통합 예시",
    description="기존 FastAPI 서버에 이상 탐지 기능을 추가한 예시",
    version="1.0.0"
)

# 요청 데이터 모델 (기존 서버의 데이터 형식에 맞춰 조정)
class SensorDataRequest(BaseModel):
    device_id: str                    # 기존 서버의 디바이스 ID
    power_W: float                   # 전력 데이터
    timestamp: Optional[str] = None  # 타임스탬프
    temp_C: Optional[float] = None   # 온도
    humidity: Optional[float] = None # 습도 (다른 키명 사용)
    lux: Optional[float] = None      # 조도
    
    # 기존 서버의 추가 필드들
    location: Optional[str] = None
    user_id: Optional[str] = None

# =============================================================================
# 이상 탐지 매니저 초기화
# =============================================================================

# 전역 탐지 매니저 (서버 시작 시 한 번만 초기화)
detector_manager = None

async def alert_handler(result: DetectionResult):
    """
    이상 탐지 시 호출되는 핸들러
    실제 서버에서는 여기에 알림 로직 추가 (이메일, Slack, DB 저장 등)
    """
    print(f"🚨 [{result.timestamp}] 이상 탐지 알림!")
    for event in result.events:
        print(f"   • {event['type']} ({event['severity']})")
    
    # 여기에 실제 알림 로직 추가
    # await send_slack_notification(result)
    # await save_to_database(result)
    # await send_email_alert(result)

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 이상 탐지 매니저 초기화"""
    global detector_manager
    
    try:
        detector_manager = AnomalyDetectorManager(
            baseline_file="ewma_baseline_ch01.json",
            alert_callback=alert_handler,
            log_level="INFO"
        )
        print("✅ 이상 탐지 시스템 초기화 완료")
    except Exception as e:
        print(f"❌ 이상 탐지 시스템 초기화 실패: {e}")
        # 이상 탐지 없이도 서버는 동작하도록 함
        detector_manager = None

# =============================================================================
# API 엔드포인트들
# =============================================================================

@app.post("/api/sensor-data")
async def receive_sensor_data(data: SensorDataRequest, background_tasks: BackgroundTasks):
    """
    기존 센서 데이터 수신 엔드포인트에 이상 탐지 기능 추가
    """
    try:
        # 1. 기존 서버 로직 (예: DB 저장, 검증 등)
        print(f"📡 센서 데이터 수신: {data.device_id} - {data.power_W}W")
        
        # 여기에 기존 서버의 로직 추가
        # await save_to_database(data)
        # await validate_device(data.device_id)
        
        # 2. 이상 탐지 수행 (선택적)
        detection_result = None
        if detector_manager:
            # 데이터 형식 변환 (기존 서버 형식 → 탐지 패키지 형식)
            detection_data = {
                "power_W": data.power_W,
                "timestamp": data.timestamp,
                "temp_C": data.temp_C,
                "rh_pct": data.humidity,  # 키명 변환
                "lux": data.lux
            }
            
            detection_result = await detector_manager.process_data(detection_data)
        
        # 3. 응답 구성
        response = {
            "status": "success",
            "device_id": data.device_id,
            "timestamp": datetime.now().isoformat(),
            "data_received": True,
        }
        
        # 이상 탐지 결과 추가
        if detection_result:
            response["anomaly_detection"] = {
                "is_anomaly": detection_result.is_anomaly,
                "events_count": len(detection_result.events),
                "events": detection_result.events,
                "stats": detection_result.stats
            }
        
        return response
        
    except Exception as e:
        print(f"❌ 데이터 처리 오류: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/anomaly-status")
async def get_anomaly_status():
    """
    이상 탐지 시스템 상태 확인 엔드포인트
    """
    if not detector_manager:
        return {"status": "disabled", "message": "이상 탐지 시스템이 비활성화되어 있습니다."}
    
    try:
        status = detector_manager.get_status()
        return {
            "status": "active",
            "detector_info": status,
            "message": "이상 탐지 시스템이 정상 작동 중입니다."
        }
    except Exception as e:
        return {"status": "error", "message": f"상태 확인 오류: {e}"}

@app.post("/api/test-anomaly")
async def test_anomaly_detection(test_power: float = 8000):
    """
    이상 탐지 테스트 엔드포인트 (개발/테스트용)
    """
    if not detector_manager:
        raise HTTPException(status_code=503, detail="이상 탐지 시스템이 비활성화되어 있습니다.")
    
    try:
        # 테스트 데이터 생성
        test_data = {
            "power_W": test_power,
            "temp_C": 25,
            "lux": 100,
            "timestamp": datetime.now().isoformat()
        }
        
        result = await detector_manager.process_data(test_data)
        
        return {
            "test_data": test_data,
            "detection_result": result.to_dict(),
            "message": f"테스트 완료 - {'이상 탐지!' if result.is_anomaly else '정상'}"
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"테스트 실패: {e}")

# =============================================================================
# 기존 서버의 다른 엔드포인트들 (예시)
# =============================================================================

@app.get("/api/devices")
async def list_devices():
    """기존 서버의 디바이스 목록 엔드포인트 (예시)"""
    return {
        "devices": [
            {"id": "device_001", "name": "메인 전력계", "status": "active"},
            {"id": "device_002", "name": "서브 전력계", "status": "active"},
        ]
    }

@app.get("/api/dashboard-data")
async def get_dashboard_data():
    """기존 서버의 대시보드 데이터 엔드포인트에 이상 탐지 정보 추가"""
    
    # 기존 대시보드 데이터
    dashboard_data = {
        "total_devices": 2,
        "active_devices": 2,
        "last_updated": datetime.now().isoformat(),
        # ... 기존 데이터들
    }
    
    # 이상 탐지 정보 추가
    if detector_manager:
        anomaly_status = detector_manager.get_status()
        dashboard_data["anomaly_detection"] = {
            "enabled": True,
            "total_processed": anomaly_status["total_processed"],
            "total_anomalies": anomaly_status["total_anomalies"],
            "anomaly_rate": anomaly_status["anomaly_rate"],
            "uptime_minutes": anomaly_status["uptime_minutes"]
        }
    else:
        dashboard_data["anomaly_detection"] = {"enabled": False}
    
    return dashboard_data

# =============================================================================
# 서버 실행 (개발용)
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 통합 서버 시작")
    print("📡 API 문서: http://localhost:8001/docs")
    print("🔍 이상 탐지 상태: http://localhost:8001/api/anomaly-status")
    print("🧪 테스트: http://localhost:8001/api/test-anomaly")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,  # 기존 서버와 다른 포트 사용
        log_level="info"
    )
