#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실시간 EWMA 기반 이상 탐지 서버

이 서버는 실시간으로 센서 데이터를 받아서 즉시 이상 징후를 탐지하고 결과를 출력합니다.
HTTP API와 WebSocket을 통해 데이터를 받을 수 있습니다.

주요 기능:
- 실시간 센서 데이터 수신 (HTTP POST, WebSocket)
- 즉시 이상 징후 탐지 및 알림
- 실시간 상태 모니터링
- 간단한 웹 인터페이스 제공

사용법:
1. python realtime_anomaly_server.py 실행
2. http://localhost:8000 에서 웹 인터페이스 접근
3. POST /api/data 또는 WebSocket /ws 로 데이터 전송

작성자: AI Assistant
버전: v1.0
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import asyncio
import json
from datetime import datetime
from typing import Optional, List
import pandas as pd

# 기존 탐지 엔진 임포트
from home_env_power_detector_v3 import StreamingDetector, EWMABaseline, Config, Event

# =============================================================================
# 데이터 모델 정의
# =============================================================================

class SensorData(BaseModel):
    """
    실시간 센서 데이터 모델
    """
    timestamp: Optional[str] = None  # ISO 형식 타임스탬프 (없으면 현재 시간 사용)
    power_W: float                   # 전력 사용량 (W) - 필수
    temp_C: Optional[float] = None   # 실내 온도 (°C)
    rh_pct: Optional[float] = None   # 상대 습도 (%)
    lux: Optional[float] = None      # 조도 (lux)
    outdoor_temp_C: Optional[float] = None  # 외부 온도 (°C)

class DetectionResult(BaseModel):
    """
    탐지 결과 모델
    """
    timestamp: str
    events: List[dict]
    sensor_data: dict
    stats: dict

# =============================================================================
# 실시간 이상 탐지 서버 클래스
# =============================================================================

class RealtimeAnomalyServer:
    """
    실시간 이상 탐지 서버
    """
    
    def __init__(self, baseline_file: str = "ewma_baseline_ch01.json", config: Optional[Config] = None):
        """
        서버 초기화
        
        Args:
            baseline_file: EWMA 베이스라인 파일 경로
            config: 탐지 설정 (없으면 기본값 사용)
        """
        print("🚀 실시간 이상 탐지 서버 초기화 중...")
        
        # 베이스라인 로드
        try:
            self.baseline = EWMABaseline.from_json(baseline_file)
            print(f"✅ 베이스라인 로드 완료: 평균={self.baseline.mean():.1f}W, 표준편차={self.baseline.std():.1f}W")
        except Exception as e:
            print(f"❌ 베이스라인 로드 실패: {e}")
            raise
        
        # 탐지기 초기화
        self.config = config or Config()
        self.detector = StreamingDetector(self.baseline, self.config)
        
        # 연결된 WebSocket 클라이언트들
        self.websocket_clients: List[WebSocket] = []
        
        # 통계
        self.total_data_points = 0
        self.total_events = 0
        self.start_time = datetime.now()
        
        print(f"🔍 탐지기 초기화 완료 (EWMA_k={self.config.ewma_k}, 전류한계={self.config.current_limit_A}A)")
        print("🌐 서버 준비 완료!")
    
    async def process_data(self, sensor_data: SensorData) -> DetectionResult:
        """
        센서 데이터를 처리하고 이상 탐지 수행
        
        Args:
            sensor_data: 수신된 센서 데이터
            
        Returns:
            탐지 결과
        """
        # 타임스탬프 처리
        if sensor_data.timestamp:
            try:
                ts = pd.to_datetime(sensor_data.timestamp)
            except:
                ts = pd.Timestamp.now()
        else:
            ts = pd.Timestamp.now()
        
        # 이상 탐지 수행
        events = self.detector.update(
            ts=ts,
            power_W=sensor_data.power_W,
            room_temp_C=sensor_data.temp_C,
            room_rh_pct=sensor_data.rh_pct,
            lux=sensor_data.lux,
            outdoor_temp_C=sensor_data.outdoor_temp_C
        )
        
        # 통계 업데이트
        self.total_data_points += 1
        self.total_events += len(events)
        
        # 현재 통계 계산
        current_stats = self.detector._stats()
        
        # 결과 구성
        result = DetectionResult(
            timestamp=ts.isoformat(),
            events=[{
                "type": event.type,
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
                "severity": event.severity,
                "info": event.info
            } for event in events],
            sensor_data=sensor_data.dict(),
            stats={
                "current_mean_W": round(current_stats[0], 2),
                "current_std_W": round(current_stats[1], 2),
                "total_data_points": self.total_data_points,
                "total_events": self.total_events,
                "uptime_minutes": round((datetime.now() - self.start_time).total_seconds() / 60, 1)
            }
        )
        
        # 이벤트가 있으면 콘솔에 출력
        if events:
            print(f"\n🚨 [{ts.strftime('%H:%M:%S')}] 이상 탐지!")
            for event in events:
                severity_icon = "🚨" if event.severity == "alert" else "⚠️"
                print(f"   {severity_icon} {event.type} ({event.severity})")
                print(f"      상세: {event.info}")
        else:
            # 주기적으로 정상 상태도 출력 (매 10개 데이터마다)
            if self.total_data_points % 10 == 0:
                print(f"✅ [{ts.strftime('%H:%M:%S')}] 정상 - 전력: {sensor_data.power_W}W, 처리완료: {self.total_data_points}개")
        
        return result
    
    async def broadcast_to_websockets(self, result: DetectionResult):
        """
        모든 WebSocket 클라이언트에게 결과 브로드캐스트
        """
        if self.websocket_clients:
            message = result.json()
            disconnected_clients = []
            
            for client in self.websocket_clients:
                try:
                    await client.send_text(message)
                except:
                    disconnected_clients.append(client)
            
            # 연결이 끊어진 클라이언트 제거
            for client in disconnected_clients:
                self.websocket_clients.remove(client)

# =============================================================================
# FastAPI 서버 설정
# =============================================================================

# 서버 인스턴스 생성
server = RealtimeAnomalyServer()

# FastAPI 앱 생성
app = FastAPI(
    title="실시간 EWMA 이상 탐지 서버",
    description="전력 및 환경 센서 데이터의 실시간 이상 징후 탐지",
    version="1.0.0"
)

# =============================================================================
# API 엔드포인트
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """
    간단한 모니터링 대시보드 HTML 반환
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>실시간 이상 탐지 모니터</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
            .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
            .stat-card { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .stat-value { font-size: 24px; font-weight: bold; color: #3498db; }
            .stat-label { color: #7f8c8d; font-size: 14px; }
            .events { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .event { padding: 10px; margin: 10px 0; border-left: 4px solid #e74c3c; background: #fdf2f2; }
            .event.normal { border-left-color: #27ae60; background: #f8fff8; }
            .test-section { background: white; padding: 20px; border-radius: 8px; margin-top: 20px; }
            input, button { padding: 8px; margin: 5px; border: 1px solid #ddd; border-radius: 4px; }
            button { background: #3498db; color: white; cursor: pointer; }
            button:hover { background: #2980b9; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🔍 실시간 EWMA 이상 탐지 시스템</h1>
                <p>전력 및 환경 센서 데이터의 실시간 모니터링</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value" id="dataPoints">0</div>
                    <div class="stat-label">처리된 데이터</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="totalEvents">0</div>
                    <div class="stat-label">탐지된 이벤트</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="uptime">0</div>
                    <div class="stat-label">가동 시간 (분)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="currentPower">-</div>
                    <div class="stat-label">현재 전력 (W)</div>
                </div>
            </div>
            
            <div class="events">
                <h3>📊 실시간 이벤트 로그</h3>
                <div id="eventLog">시스템 대기 중...</div>
            </div>
            
            <div class="test-section">
                <h3>🧪 테스트 데이터 전송</h3>
                <input type="number" id="testPower" placeholder="전력 (W)" value="1000">
                <input type="number" id="testTemp" placeholder="온도 (°C)" value="25">
                <input type="number" id="testLux" placeholder="조도 (lux)" value="100">
                <button onclick="sendTestData()">데이터 전송</button>
                <button onclick="sendAnomalyData()">이상 데이터 전송 (테스트)</button>
            </div>
        </div>
        
        <script>
            // WebSocket 연결
            const ws = new WebSocket('ws://localhost:8000/ws');
            const eventLog = document.getElementById('eventLog');
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                updateStats(data.stats);
                updateEventLog(data);
            };
            
            function updateStats(stats) {
                document.getElementById('dataPoints').textContent = stats.total_data_points;
                document.getElementById('totalEvents').textContent = stats.total_events;
                document.getElementById('uptime').textContent = stats.uptime_minutes;
            }
            
            function updateEventLog(data) {
                const timestamp = new Date(data.timestamp).toLocaleTimeString();
                document.getElementById('currentPower').textContent = data.sensor_data.power_W;
                
                let logEntry = '';
                if (data.events.length > 0) {
                    logEntry = `<div class="event">🚨 [${timestamp}] 이상 탐지!<br>`;
                    data.events.forEach(event => {
                        const icon = event.severity === 'alert' ? '🚨' : '⚠️';
                        logEntry += `${icon} ${event.type} (${event.severity})<br>`;
                    });
                    logEntry += '</div>';
                } else {
                    logEntry = `<div class="event normal">✅ [${timestamp}] 정상 - 전력: ${data.sensor_data.power_W}W</div>`;
                }
                
                eventLog.innerHTML = logEntry + eventLog.innerHTML;
                
                // 최대 20개 로그만 유지
                const logs = eventLog.children;
                while (logs.length > 20) {
                    eventLog.removeChild(logs[logs.length - 1]);
                }
            }
            
            function sendTestData() {
                const power = document.getElementById('testPower').value;
                const temp = document.getElementById('testTemp').value;
                const lux = document.getElementById('testLux').value;
                
                fetch('/api/data', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        power_W: parseFloat(power),
                        temp_C: parseFloat(temp),
                        lux: parseFloat(lux)
                    })
                });
            }
            
            function sendAnomalyData() {
                // 이상 데이터 전송 (높은 전력)
                fetch('/api/data', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        power_W: 8000,  // 높은 전력으로 이상 상황 시뮬레이션
                        temp_C: 25,
                        lux: 100
                    })
                });
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/data")
async def receive_sensor_data(data: SensorData):
    """
    HTTP POST로 센서 데이터 수신 및 처리
    """
    try:
        result = await server.process_data(data)
        await server.broadcast_to_websockets(result)
        return {"status": "success", "result": result}
    except Exception as e:
        print(f"❌ 데이터 처리 오류: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 연결 처리
    """
    await websocket.accept()
    server.websocket_clients.append(websocket)
    print(f"🔌 WebSocket 클라이언트 연결: {len(server.websocket_clients)}개 활성")
    
    try:
        while True:
            # 클라이언트로부터 데이터 수신
            data = await websocket.receive_text()
            try:
                sensor_data = SensorData.parse_raw(data)
                result = await server.process_data(sensor_data)
                await server.broadcast_to_websockets(result)
            except Exception as e:
                await websocket.send_text(json.dumps({"error": str(e)}))
    except WebSocketDisconnect:
        server.websocket_clients.remove(websocket)
        print(f"🔌 WebSocket 클라이언트 연결 해제: {len(server.websocket_clients)}개 활성")

@app.get("/api/status")
async def get_status():
    """
    서버 상태 정보 반환
    """
    current_stats = server.detector._stats()
    return {
        "status": "running",
        "uptime_minutes": round((datetime.now() - server.start_time).total_seconds() / 60, 1),
        "total_data_points": server.total_data_points,
        "total_events": server.total_events,
        "websocket_clients": len(server.websocket_clients),
        "detector_stats": {
            "current_mean_W": round(current_stats[0], 2),
            "current_std_W": round(current_stats[1], 2)
        },
        "config": {
            "ewma_k": server.config.ewma_k,
            "current_limit_A": server.config.current_limit_A,
            "spike_delta_A": server.config.spike_delta_A
        }
    }

# =============================================================================
# 서버 실행
# =============================================================================

if __name__ == "__main__":
    print("="*80)
    print("🚀 실시간 EWMA 이상 탐지 서버 시작")
    print("="*80)
    print("📡 HTTP API: http://localhost:8000/api/data")
    print("🌐 웹 대시보드: http://localhost:8000")
    print("🔌 WebSocket: ws://localhost:8000/ws")
    print("📊 상태 확인: http://localhost:8000/api/status")
    print("="*80)
    
    # 서버 실행
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
