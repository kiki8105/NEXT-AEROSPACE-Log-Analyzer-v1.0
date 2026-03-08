# src/engines/io_engine.py

import os
import sys
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
if src_dir not in sys.path:
    sys.path.append(src_dir)

from engines.parser import ULGParser
from storage.parquet_cache import ParquetCacheManager

class LogIOEngine:
    """
    로그 파일을 읽어올 때 캐시가 있으면 0.1초만에 불러오고,
    없으면 파싱 후 저장하는 '스마트 로딩'을 수행하는 전체 시스템 입출력 관리자입니다.
    """
    def __init__(self):
        self.parser = ULGParser()
        self.cache_mgr = ParquetCacheManager()

    def load(self, file_path: str):
        log_filename = os.path.basename(file_path)
        
        start_time = time.time()
        
        # 1. 캐시가 있는지 확인
        if self.cache_mgr.is_cached(log_filename):
            dataset = self.cache_mgr.load_dataset(log_filename)
            load_type = "Cache Load"
        else:
            # 2. 캐시가 없으면 ULG 파싱 수행
            dataset = self.parser.parse(file_path)
            # 3. 파싱 후 다음을 위해 저장
            self.cache_mgr.save_dataset(dataset, log_filename)
            load_type = "Full Parsing"
            
        end_time = time.time()
        print(f"\n[{load_type}] 완료 시간: {end_time - start_time:.4f} 초")
        return dataset

# === 단독 테스트 실행 ===
if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(src_dir, "../"))
    
    # ⚠️ 이전 단계에서 성공했던 파일 이름을 똑같이 적어주세요!
    test_file = os.path.join(project_root, "data", "raw", "sample.ulg") 
    
    io_engine = LogIOEngine()
    
    print("=== 첫 번째 로딩 시도 (캐시 생성) ===")
    dataset1 = io_engine.load(test_file)
    
    print("\n=== 두 번째 로딩 시도 (캐시 로딩 - 속도 체감) ===")
    dataset2 = io_engine.load(test_file)