#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실시간 이상 탐지 서버 테스트 클라이언트

이 클라이언트는 실시간 서버에 테스트 데이터를 전송하여 
이상 탐지 기능을 테스트합니다.

사용법:
1. realtime_anomaly_server.py 실행
2. python test_client.py 실행
3. 다양한 테스트 시나리오 실행

작성자: AI Assistant
"""

import requests
import asyncio
import websockets
import json
import time
import random
from datetime import datetime
from typing import List, Dict

class AnomalyTestClient:
    """
    이상 탐지 서버 테스트 클라이언트
    """
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        self.server_url = server_url
        self.api_url = f"{server_url}/api/data"
        self.ws_url = server_url.replace("http", "ws") + "/ws"
    
    def send_http_data(self, power_W: float, temp_C: float = 25.0, lux: float = 100.0) -> Dict:
        """
        HTTP POST로 데이터 전송
        """
        data = {
            "power_W": power_W,
            "temp_C": temp_C,
            "lux": lux,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            response = requests.post(self.api_url, json=data, timeout=5)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ HTTP 오류: {response.status_code}")
                return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            print(f"❌ 연결 오류: {e}")
            return {"error": str(e)}
    
    async def send_websocket_data(self, data_points: List[Dict]):
        """
        WebSocket으로 데이터 스트리밍
        """
        try:
            async with websockets.connect(self.ws_url) as websocket:
                print(f"🔌 WebSocket 연결 성공: {self.ws_url}")
                
                for i, data in enumerate(data_points):
                    await websocket.send(json.dumps(data))
                    print(f"📤 [{i+1}/{len(data_points)}] 전송: 전력={data['power_W']}W")
                    
                    # 응답 수신 (논블로킹)
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        result = json.loads(response)
                        if result.get("events"):
                            print(f"🚨 이상 탐지: {len(result['events'])}개 이벤트")
                    except asyncio.TimeoutError:
                        pass
                    
                    await asyncio.sleep(2)  # 2초 간격
                
        except Exception as e:
            print(f"❌ WebSocket 오류: {e}")
    
    def test_normal_data(self, count: int = 10):
        """
        정상 데이터 테스트
        """
        print(f"\n✅ 정상 데이터 테스트 ({count}개)")
        print("-" * 50)
        
        for i in range(count):
            # 정상 범위의 전력 데이터 (900-1100W)
            power = random.uniform(900, 1100)
            temp = random.uniform(20, 30)
            lux = random.uniform(50, 200)
            
            result = self.send_http_data(power, temp, lux)
            if "error" not in result:
                events = result.get("result", {}).get("events", [])
                status = "🚨 이상!" if events else "✅ 정상"
                print(f"[{i+1:2d}] {power:6.1f}W, {temp:4.1f}°C, {lux:5.1f}lux → {status}")
            
            time.sleep(1)
    
    def test_anomaly_data(self):
        """
        이상 데이터 테스트
        """
        print(f"\n🚨 이상 데이터 테스트")
        print("-" * 50)
        
        anomaly_cases = [
            {"name": "과전류 (높은 전력)", "power": 8000, "temp": 25, "lux": 100},
            {"name": "전류 스파이크", "power": 9900, "temp": 25, "lux": 100},
            {"name": "급격한 변화", "power": 500, "temp": 25, "lux": 100},
            {"name": "매우 높은 전력", "power": 12000, "temp": 25, "lux": 100},
        ]
        
        for i, case in enumerate(anomaly_cases):
            print(f"\n[{i+1}] {case['name']} 테스트")
            result = self.send_http_data(case["power"], case["temp"], case["lux"])
            
            if "error" not in result:
                events = result.get("result", {}).get("events", [])
                if events:
                    print(f"   🚨 탐지된 이벤트: {len(events)}개")
                    for event in events:
                        print(f"      • {event['type']} ({event['severity']})")
                else:
                    print("   ✅ 이상 없음 (예상과 다름)")
            else:
                print(f"   ❌ 오류: {result['error']}")
            
            time.sleep(2)
    
    async def test_continuous_streaming(self, duration_minutes: int = 5):
        """
        연속 스트리밍 테스트
        """
        print(f"\n📡 연속 스트리밍 테스트 ({duration_minutes}분)")
        print("-" * 50)
        
        data_points = []
        end_time = time.time() + (duration_minutes * 60)
        
        while time.time() < end_time:
            # 가끔 이상 데이터 포함 (10% 확률)
            if random.random() < 0.1:
                power = random.choice([8000, 500, 9900])  # 이상 데이터
            else:
                power = random.uniform(900, 1100)  # 정상 데이터
            
            data_points.append({
                "power_W": power,
                "temp_C": random.uniform(20, 30),
                "lux": random.uniform(50, 200),
                "timestamp": datetime.now().isoformat()
            })
            
            if len(data_points) >= 50:  # 50개씩 배치로 전송
                break
        
        await self.send_websocket_data(data_points)
    
    def check_server_status(self):
        """
        서버 상태 확인
        """
        try:
            response = requests.get(f"{self.server_url}/api/status", timeout=5)
            if response.status_code == 200:
                status = response.json()
                print("\n📊 서버 상태:")
                print("-" * 30)
                print(f"상태: {status['status']}")
                print(f"가동 시간: {status['uptime_minutes']:.1f}분")
                print(f"처리된 데이터: {status['total_data_points']}개")
                print(f"탐지된 이벤트: {status['total_events']}개")
                print(f"WebSocket 클라이언트: {status['websocket_clients']}개")
                print(f"현재 평균 전력: {status['detector_stats']['current_mean_W']}W")
                return True
            else:
                print(f"❌ 서버 상태 확인 실패: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ 서버 연결 실패: {e}")
            return False

def main():
    """
    메인 테스트 함수
    """
    print("="*80)
    print("🧪 실시간 이상 탐지 서버 테스트 클라이언트")
    print("="*80)
    
    client = AnomalyTestClient()
    
    # 서버 상태 확인
    if not client.check_server_status():
        print("\n❌ 서버가 실행되지 않았습니다.")
        print("💡 먼저 'python realtime_anomaly_server.py'를 실행해주세요.")
        return
    
    while True:
        print("\n" + "="*50)
        print("테스트 메뉴:")
        print("1. 정상 데이터 테스트 (10개)")
        print("2. 이상 데이터 테스트")
        print("3. 연속 스트리밍 테스트 (5분)")
        print("4. 서버 상태 확인")
        print("5. 종료")
        print("="*50)
        
        try:
            choice = input("선택하세요 (1-5): ").strip()
            
            if choice == "1":
                client.test_normal_data(10)
            elif choice == "2":
                client.test_anomaly_data()
            elif choice == "3":
                print("📡 WebSocket 스트리밍 시작...")
                asyncio.run(client.test_continuous_streaming(5))
            elif choice == "4":
                client.check_server_status()
            elif choice == "5":
                print("👋 테스트 클라이언트 종료")
                break
            else:
                print("❌ 잘못된 선택입니다.")
                
        except KeyboardInterrupt:
            print("\n\n👋 테스트 중단됨")
            break
        except Exception as e:
            print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    main()
