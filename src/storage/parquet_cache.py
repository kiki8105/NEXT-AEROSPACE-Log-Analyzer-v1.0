# src/storage/parquet_cache.py

import os
import sys
import time
import polars as pl

# 상위 폴더(src) 인식용 코드
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
if src_dir not in sys.path:
    sys.path.append(src_dir)

from core.log_model import LogDataset, TopicInstance, Signal

class ParquetCacheManager:
    """
    파싱이 끝난 LogDataset을 고속 로딩이 가능한 Parquet 포맷으로 저장하고 불러옵니다.
    """
    def __init__(self, cache_dir=".cache"):
        # 프로젝트 최상단 폴더 위치를 찾아 .cache 폴더를 지정합니다.
        project_root = os.path.abspath(os.path.join(src_dir, "../"))
        self.cache_dir = os.path.join(project_root, cache_dir)
        
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def save_dataset(self, dataset: LogDataset, log_filename: str):
        """
        데이터셋의 모든 Topic을 개별 Parquet 파일로 저장합니다.
        """
        # 로그 파일 이름으로 캐시 전용 폴더 생성 (예: .cache/sample_ulg)
        safe_name = log_filename.replace('.', '_')
        log_cache_dir = os.path.join(self.cache_dir, safe_name)
        
        if not os.path.exists(log_cache_dir):
            os.makedirs(log_cache_dir)

        print(f"[{log_filename}] 캐시 데이터를 디스크에 저장합니다...")
        
        # 데이터셋 안의 모든 Topic을 순회하며 저장
        for unique_name, topic_inst in dataset.topics.items():
            file_path = os.path.join(log_cache_dir, f"{unique_name}.parquet")
            # Polars의 초고속 Parquet 저장 기능 사용
            topic_inst.dataframe.write_parquet(file_path)
            
        print(f"[저장 완료] 경로: {log_cache_dir}")

    def load_dataset(self, log_filename: str) -> LogDataset:
        """
        저장된 Parquet 파일들을 읽어 다시 완벽한 LogDataset으로 복원합니다.
        """
        safe_name = log_filename.replace('.', '_')
        log_cache_dir = os.path.join(self.cache_dir, safe_name)
        
        if not os.path.exists(log_cache_dir):
            return None # 캐시가 없으면 None 반환
            
        print(f"[{log_filename}] 캐시 데이터를 불러옵니다. (초고속 모드)")
        dataset = LogDataset()
        
        # 캐시 폴더 안의 모든 .parquet 파일 읽기
        for file_name in os.listdir(log_cache_dir):
            if file_name.endswith(".parquet"):
                # 파일명 분리 (예: 'sensor_gyro_0.parquet' -> 'sensor_gyro', 0)
                unique_name = file_name.replace(".parquet", "")
                parts = unique_name.split('_')
                instance_id = int(parts[-1])
                base_name = "_".join(parts[:-1])
                
                # 데이터 프레임 로드
                file_path = os.path.join(log_cache_dir, file_name)
                df = pl.read_parquet(file_path)
                
                # TopicInstance 박스 재조립
                topic_inst = TopicInstance(base_name, instance_id, dataframe=df)
                
                # Signal 선들 재조립
                for col_name in df.columns:
                    if col_name not in ["timestamp", "timestamp_sec"]:
                        topic_inst.signals[col_name] = Signal(name=col_name, data=df[col_name])
                
                dataset.add_topic(topic_inst)
                
        return dataset

    def is_cached(self, log_filename: str) -> bool:
        """이 로그 파일이 이미 캐시되어 있는지 확인합니다."""
        safe_name = log_filename.replace('.', '_')
        return os.path.exists(os.path.join(self.cache_dir, safe_name))