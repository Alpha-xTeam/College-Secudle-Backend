#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار الضغط على النظام - إصدار مبسط
أداة لاختبار قدرة النظام على التعامل مع طلبات متعددة متزامنة باستخدام threading
"""

import requests
import threading
import time
import json
from datetime import datetime
import statistics

class SimpleStressTest:
    def __init__(self, base_url="http://localhost:5000", concurrent_requests=30):
        self.base_url = base_url
        self.concurrent_requests = concurrent_requests
        self.results = []
        self.lock = threading.Lock()
        
    def make_request(self, endpoint, method="GET", data=None, headers=None, thread_id=None):
        """إرسال طلب HTTP واحد"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            if headers is None:
                headers = {'User-Agent': 'StressTest/1.0'}
            
            if method.upper() == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=30)
            else:
                response = requests.get(url, headers=headers, timeout=30)
                
            response_time = time.time() - start_time
            
            result = {
                "thread_id": thread_id,
                "status_code": response.status_code,
                "response_time": response_time,
                "success": True,
                "endpoint": endpoint,
                "method": method,
                "error": None,
                "content_length": len(response.text),
                "timestamp": datetime.now().strftime('%H:%M:%S.%f')[:-3]
            }
            
        except Exception as e:
            response_time = time.time() - start_time
            result = {
                "thread_id": thread_id,
                "status_code": 0,
                "response_time": response_time,
                "success": False,
                "endpoint": endpoint,
                "method": method,
                "error": str(e),
                "content_length": 0,
                "timestamp": datetime.now().strftime('%H:%M:%S.%f')[:-3]
            }
        
        # إضافة النتيجة بشكل آمن
        with self.lock:
            self.results.append(result)
        
        return result

    def run_concurrent_requests(self, endpoint, method="GET", data=None):
        """تشغيل طلبات متزامنة باستخدام threads"""
        print(f"🚀 بدء اختبار {self.concurrent_requests} طلب متزامن على {endpoint}")
        print(f"⏰ الوقت: {datetime.now().strftime('%H:%M:%S')}")
        
        # إعادة تعيين النتائج
        self.results = []
        
        # إنشاء threads
        threads = []
        start_time = time.time()
        
        for i in range(self.concurrent_requests):
            thread = threading.Thread(
                target=self.make_request,
                args=(endpoint, method, data, None, i+1)
            )
            threads.append(thread)
        
        # بدء جميع الـ threads
        for thread in threads:
            thread.start()
        
        # انتظار انتهاء جميع الـ threads
        for thread in threads:
            thread.join()
        
        total_time = time.time() - start_time
        
        return self.results.copy(), total_time

    def analyze_results(self, results, total_time, endpoint):
        """تحليل النتائج"""
        successful_requests = [r for r in results if r.get('success', False)]
        failed_requests = [r for r in results if not r.get('success', False)]
        
        print(f"\n📊 تحليل النتائج لـ {endpoint}")
        print("=" * 60)
        
        print(f"⏱️  إجمالي الوقت: {total_time:.2f} ثانية")
        print(f"📝 إجمالي الطلبات: {len(results)}")
        print(f"✅ الطلبات الناجحة: {len(successful_requests)}")
        print(f"❌ الطلبات الفاشلة: {len(failed_requests)}")
        
        if successful_requests:
            response_times = [r['response_time'] for r in successful_requests]
            status_codes = {}
            
            for r in successful_requests:
                code = r['status_code']
                status_codes[code] = status_codes.get(code, 0) + 1
            
            print(f"\n⚡ أوقات الاستجابة:")
            print(f"   - المتوسط: {statistics.mean(response_times):.3f} ثانية")
            print(f"   - الوسيط: {statistics.median(response_times):.3f} ثانية")
            print(f"   - الأسرع: {min(response_times):.3f} ثانية")
            print(f"   - الأبطأ: {max(response_times):.3f} ثانية")
            
            if len(response_times) > 1:
                print(f"   - الانحراف المعياري: {statistics.stdev(response_times):.3f} ثانية")
            
            print(f"\n📋 رموز الحالة:")
            for code, count in status_codes.items():
                emoji = "✅" if 200 <= code < 300 else "⚠️" if 300 <= code < 400 else "❌"
                print(f"   {emoji} {code}: {count} طلب")
            
            # حساب الطلبات في الثانية
            rps = len(successful_requests) / total_time
            print(f"\n🔥 الطلبات في الثانية: {rps:.2f}")
            
            # عرض تفاصيل أول 5 طلبات ناجحة
            print(f"\n📋 عينة من الطلبات الناجحة (أول 5):")
            for i, r in enumerate(successful_requests[:5]):
                print(f"   {i+1}. Thread {r['thread_id']}: {r['status_code']} - {r['response_time']:.3f}s - {r['timestamp']}")
        
        if failed_requests:
            print(f"\n💥 تفاصيل الأخطاء:")
            error_counts = {}
            for r in failed_requests:
                error = r.get('error', 'خطأ غير معروف')
                error_counts[error] = error_counts.get(error, 0) + 1
            
            for error, count in error_counts.items():
                print(f"   - {error}: {count} مرة")
        
        # تحليل التوزيع الزمني
        if successful_requests:
            print(f"\n⏱️ التوزيع الزمني للطلبات:")
            sorted_requests = sorted(successful_requests, key=lambda x: x['response_time'])
            percentiles = [50, 75, 90, 95, 99]
            
            for p in percentiles:
                if len(sorted_requests) > 1:
                    index = int((p / 100) * (len(sorted_requests) - 1))
                    time_val = sorted_requests[index]['response_time']
                    print(f"   - {p}%: {time_val:.3f} ثانية")
        
        return {
            "endpoint": endpoint,
            "total_time": total_time,
            "total_requests": len(results),
            "successful": len(successful_requests),
            "failed": len(failed_requests),
            "success_rate": (len(successful_requests) / len(results) * 100) if results else 0,
            "rps": len(successful_requests) / total_time if total_time > 0 else 0,
            "avg_response_time": statistics.mean([r['response_time'] for r in successful_requests]) if successful_requests else 0,
            "median_response_time": statistics.median([r['response_time'] for r in successful_requests]) if successful_requests else 0,
            "max_response_time": max([r['response_time'] for r in successful_requests]) if successful_requests else 0,
            "min_response_time": min([r['response_time'] for r in successful_requests]) if successful_requests else 0
        }

    def run_multiple_tests(self):
        """تشغيل عدة اختبارات على endpoints مختلفة"""
        
        # قائمة الـ endpoints للاختبار
        test_cases = [
            {"endpoint": "/", "method": "GET", "name": "الصفحة الرئيسية"},
            {"endpoint": "/api/health", "method": "GET", "name": "فحص صحة النظام"},
            {"endpoint": "/api/departments", "method": "GET", "name": "قائمة الأقسام"},
            {"endpoint": "/api/rooms", "method": "GET", "name": "قائمة القاعات"},
            {"endpoint": "/api/schedule/current", "method": "GET", "name": "الجدول الحالي"},
        ]
        
        print("🎯 بدء اختبار الضغط على النظام")
        print(f"🌐 الخادم: {self.base_url}")
        print(f"🔢 عدد الطلبات المتزامنة: {self.concurrent_requests}")
        print("=" * 60)
        
        all_results = []
        
        for i, test_case in enumerate(test_cases, 1):
            endpoint = test_case["endpoint"]
            method = test_case["method"]
            name = test_case.get("name", endpoint)
            
            print(f"\n🧪 الاختبار {i}/{len(test_cases)}: {name}")
            print("-" * 40)
            
            try:
                results, total_time = self.run_concurrent_requests(endpoint, method)
                analysis = self.analyze_results(results, total_time, endpoint)
                analysis["test_name"] = name
                all_results.append(analysis)
                
                # وقفة قصيرة بين الاختبارات
                if i < len(test_cases):
                    print("\n⏳ انتظار 3 ثوانٍ قبل الاختبار التالي...")
                    time.sleep(3)
                
            except Exception as e:
                print(f"❌ خطأ في اختبار {endpoint}: {str(e)}")
        
        # ملخص عام
        self.print_summary(all_results)
        
        return all_results

    def print_summary(self, all_results):
        """طباعة الملخص العام"""
        print("\n" + "=" * 60)
        print("📈 الملخص العام لجميع الاختبارات")
        print("=" * 60)
        
        if not all_results:
            print("❌ لا توجد نتائج للعرض")
            return
        
        total_requests = sum([r["total_requests"] for r in all_results])
        total_successful = sum([r["successful"] for r in all_results])
        total_failed = sum([r["failed"] for r in all_results])
        avg_success_rate = sum([r["success_rate"] for r in all_results]) / len(all_results)
        total_time = sum([r["total_time"] for r in all_results])
        
        print(f"🔢 إجمالي الطلبات: {total_requests}")
        print(f"✅ إجمالي الناجحة: {total_successful}")
        print(f"❌ إجمالي الفاشلة: {total_failed}")
        print(f"📊 معدل النجاح العام: {avg_success_rate:.1f}%")
        print(f"⏱️ إجمالي وقت الاختبار: {total_time:.2f} ثانية")
        
        print(f"\n📋 تفاصيل كل اختبار:")
        print("-" * 60)
        
        for r in all_results:
            status_emoji = "✅" if r["success_rate"] > 95 else "⚠️" if r["success_rate"] > 80 else "❌"
            print(f"{status_emoji} {r['test_name']}")
            print(f"    النجاح: {r['success_rate']:.1f}% | المتوسط: {r['avg_response_time']:.3f}s | RPS: {r['rps']:.1f}")
        
        # تقييم عام للنظام
        print(f"\n🎯 التقييم العام:")
        if avg_success_rate >= 99:
            print("🌟 ممتاز: النظام يتعامل بشكل ممتاز مع الضغط")
        elif avg_success_rate >= 95:
            print("👍 جيد جداً: النظام مستقر تحت الضغط")
        elif avg_success_rate >= 90:
            print("👌 جيد: النظام يعمل بشكل مقبول")
        elif avg_success_rate >= 80:
            print("⚠️ متوسط: يحتاج النظام إلى تحسينات")
        else:
            print("❌ ضعيف: النظام يحتاج إلى مراجعة شاملة")

    def custom_endpoint_test(self, endpoint, method="GET", data=None):
        """اختبار endpoint محدد"""
        print(f"🎯 اختبار مخصص: {method} {endpoint}")
        
        try:
            results, total_time = self.run_concurrent_requests(endpoint, method, data)
            return self.analyze_results(results, total_time, endpoint)
        except Exception as e:
            print(f"❌ خطأ في الاختبار: {str(e)}")
            return None

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='اختبار الضغط على النظام - إصدار مبسط')
    parser.add_argument('--url', default='http://localhost:5000', help='رابط الخادم')
    parser.add_argument('--requests', type=int, default=30, help='عدد الطلبات المتزامنة')
    parser.add_argument('--endpoint', help='endpoint محدد للاختبار')
    parser.add_argument('--method', default='GET', help='نوع الطلب')
    
    args = parser.parse_args()
    
    tester = SimpleStressTest(base_url=args.url, concurrent_requests=args.requests)
    
    print("🔧 اختبار الضغط على النظام")
    print(f"📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    if args.endpoint:
        # اختبار endpoint محدد
        tester.custom_endpoint_test(args.endpoint, args.method)
    else:
        # تشغيل جميع الاختبارات
        tester.run_multiple_tests()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف الاختبار بواسطة المستخدم")
    except Exception as e:
        print(f"\n💥 خطأ في التشغيل: {str(e)}")