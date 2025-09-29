#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار الضغط على النظام
أداة لاختبار قدرة النظام على التعامل مع طلبات متعددة متزامنة
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime
import sys
import argparse

class StressTest:
    def __init__(self, base_url="http://localhost:5000", concurrent_requests=30):
        self.base_url = base_url
        self.concurrent_requests = concurrent_requests
        self.results = []
        
    async def make_request(self, session, endpoint, method="GET", data=None, headers=None):
        """إرسال طلب HTTP واحد"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            if method.upper() == "POST":
                async with session.post(url, json=data, headers=headers) as response:
                    response_time = time.time() - start_time
                    content = await response.text()
                    return {
                        "status_code": response.status,
                        "response_time": response_time,
                        "success": True,
                        "endpoint": endpoint,
                        "method": method,
                        "error": None,
                        "content_length": len(content)
                    }
            else:
                async with session.get(url, headers=headers) as response:
                    response_time = time.time() - start_time
                    content = await response.text()
                    return {
                        "status_code": response.status,
                        "response_time": response_time,
                        "success": True,
                        "endpoint": endpoint,
                        "method": method,
                        "error": None,
                        "content_length": len(content)
                    }
                    
        except Exception as e:
            response_time = time.time() - start_time
            return {
                "status_code": 0,
                "response_time": response_time,
                "success": False,
                "endpoint": endpoint,
                "method": method,
                "error": str(e),
                "content_length": 0
            }

    async def run_concurrent_requests(self, endpoint, method="GET", data=None):
        """تشغيل طلبات متزامنة"""
        print(f"🚀 بدء اختبار {self.concurrent_requests} طلب متزامن على {endpoint}")
        print(f"⏰ الوقت: {datetime.now().strftime('%H:%M:%S')}")
        
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(
            connector=connector, 
            timeout=timeout,
            headers={'User-Agent': 'StressTest/1.0'}
        ) as session:
            
            # إنشاء المهام
            tasks = []
            for i in range(self.concurrent_requests):
                task = self.make_request(session, endpoint, method, data)
                tasks.append(task)
            
            # تشغيل جميع المهام بنفس الوقت
            start_time = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_time = time.time() - start_time
            
            return results, total_time

    def analyze_results(self, results, total_time, endpoint):
        """تحليل النتائج"""
        successful_requests = [r for r in results if isinstance(r, dict) and r.get('success', False)]
        failed_requests = [r for r in results if isinstance(r, dict) and not r.get('success', False)]
        errors = [r for r in results if isinstance(r, Exception)]
        
        print(f"\n📊 تحليل النتائج لـ {endpoint}")
        print("=" * 60)
        
        print(f"⏱️  إجمالي الوقت: {total_time:.2f} ثانية")
        print(f"📝 إجمالي الطلبات: {len(results)}")
        print(f"✅ الطلبات الناجحة: {len(successful_requests)}")
        print(f"❌ الطلبات الفاشلة: {len(failed_requests)}")
        print(f"⚠️  الأخطاء: {len(errors)}")
        
        if successful_requests:
            response_times = [r['response_time'] for r in successful_requests]
            status_codes = {}
            
            for r in successful_requests:
                code = r['status_code']
                status_codes[code] = status_codes.get(code, 0) + 1
            
            print(f"\n⚡ أوقات الاستجابة:")
            print(f"   - المتوسط: {sum(response_times) / len(response_times):.3f} ثانية")
            print(f"   - الأسرع: {min(response_times):.3f} ثانية")
            print(f"   - الأبطأ: {max(response_times):.3f} ثانية")
            
            print(f"\n📋 رموز الحالة:")
            for code, count in status_codes.items():
                print(f"   - {code}: {count} طلب")
            
            # حساب الطلبات في الثانية
            rps = len(successful_requests) / total_time
            print(f"\n🔥 الطلبات في الثانية: {rps:.2f}")
        
        if failed_requests or errors:
            print(f"\n💥 تفاصيل الأخطاء:")
            for r in failed_requests:
                print(f"   - {r.get('error', 'خطأ غير معروف')}")
            for e in errors:
                print(f"   - {str(e)}")
        
        return {
            "endpoint": endpoint,
            "total_time": total_time,
            "total_requests": len(results),
            "successful": len(successful_requests),
            "failed": len(failed_requests),
            "errors": len(errors),
            "rps": len(successful_requests) / total_time if total_time > 0 else 0,
            "avg_response_time": sum([r['response_time'] for r in successful_requests]) / len(successful_requests) if successful_requests else 0
        }

    async def run_multiple_tests(self):
        """تشغيل عدة اختبارات على endpoints مختلفة"""
        
        # قائمة الـ endpoints للاختبار
        test_cases = [
            {"endpoint": "/api/health", "method": "GET"},
            {"endpoint": "/api/departments", "method": "GET"},
            {"endpoint": "/api/rooms", "method": "GET"},
            {"endpoint": "/api/schedule/current", "method": "GET"},
        ]
        
        print("🎯 بدء اختبار الضغط على النظام")
        print("=" * 60)
        
        all_results = []
        
        for test_case in test_cases:
            endpoint = test_case["endpoint"]
            method = test_case["method"]
            
            try:
                results, total_time = await self.run_concurrent_requests(endpoint, method)
                analysis = self.analyze_results(results, total_time, endpoint)
                all_results.append(analysis)
                
                # وقفة قصيرة بين الاختبارات
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"❌ خطأ في اختبار {endpoint}: {str(e)}")
        
        # ملخص عام
        print("\n" + "=" * 60)
        print("📈 الملخص العام")
        print("=" * 60)
        
        total_requests = sum([r["total_requests"] for r in all_results])
        total_successful = sum([r["successful"] for r in all_results])
        avg_rps = sum([r["rps"] for r in all_results]) / len(all_results) if all_results else 0
        
        print(f"إجمالي الطلبات: {total_requests}")
        print(f"إجمالي الناجحة: {total_successful}")
        print(f"معدل النجاح: {(total_successful/total_requests*100):.1f}%" if total_requests > 0 else "N/A")
        print(f"متوسط الطلبات/ثانية: {avg_rps:.2f}")
        
        return all_results

    async def custom_endpoint_test(self, endpoint, method="GET", data=None):
        """اختبار endpoint محدد"""
        print(f"🎯 اختبار مخصص: {method} {endpoint}")
        
        try:
            results, total_time = await self.run_concurrent_requests(endpoint, method, data)
            return self.analyze_results(results, total_time, endpoint)
        except Exception as e:
            print(f"❌ خطأ في الاختبار: {str(e)}")
            return None

async def main():
    parser = argparse.ArgumentParser(description='اختبار الضغط على النظام')
    parser.add_argument('--url', default='http://localhost:5000', help='رابط الخادم')
    parser.add_argument('--requests', type=int, default=30, help='عدد الطلبات المتزامنة')
    parser.add_argument('--endpoint', help='endpoint محدد للاختبار')
    parser.add_argument('--method', default='GET', help='نوع الطلب')
    
    args = parser.parse_args()
    
    tester = StressTest(base_url=args.url, concurrent_requests=args.requests)
    
    if args.endpoint:
        # اختبار endpoint محدد
        await tester.custom_endpoint_test(args.endpoint, args.method)
    else:
        # تشغيل جميع الاختبارات
        await tester.run_multiple_tests()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  تم إيقاف الاختبار بواسطة المستخدم")
    except Exception as e:
        print(f"\n💥 خطأ في التشغيل: {str(e)}")