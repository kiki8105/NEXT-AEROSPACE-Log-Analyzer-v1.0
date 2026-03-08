# src/engines/math_engine.py

import numpy as np
import polars as pl

class MathEngine:
    """
    PX4 로그 분석을 위한 가상 시그널(Virtual Signals) 및 주파수 변환 엔진
    """
    
    @staticmethod
    def preprocess_dataset(dataset):
        """로그 파일이 로드된 직후, 제어 분석에 필수적인 가상 데이터를 일괄 생성합니다."""
        
        # 1. Attitude (Quaternion -> Euler [deg])
        # 1-1. Actual (실제 자세)
        if "vehicle_attitude_0" in dataset.topics:
            topic = dataset.topics["vehicle_attitude_0"]
            df = topic.dataframe
            if "q[0]" in df.columns:
                q0, q1, q2, q3 = df["q[0]"].to_numpy(), df["q[1]"].to_numpy(), df["q[2]"].to_numpy(), df["q[3]"].to_numpy()
                roll = np.arctan2(2*(q0*q1 + q2*q3), 1 - 2*(q1**2 + q2**2)) * 57.2958
                pitch = np.arcsin(np.clip(2*(q0*q2 - q3*q1), -1.0, 1.0)) * 57.2958
                yaw = np.arctan2(2*(q0*q3 + q1*q2), 1 - 2*(q2**2 + q3**2)) * 57.2958
                
                topic.dataframe = df.with_columns([
                    pl.Series("roll_euler", roll), pl.Series("pitch_euler", pitch), pl.Series("yaw_euler", yaw)
                ])
                for s in ["roll_euler", "pitch_euler", "yaw_euler"]: topic.signals[s] = None

        # 1-2. Setpoint (목표 자세)
        if "vehicle_attitude_setpoint_0" in dataset.topics:
            topic = dataset.topics["vehicle_attitude_setpoint_0"]
            df = topic.dataframe
            if "q_d[0]" in df.columns:
                q0, q1, q2, q3 = df["q_d[0]"].to_numpy(), df["q_d[1]"].to_numpy(), df["q_d[2]"].to_numpy(), df["q_d[3]"].to_numpy()
                roll = np.arctan2(2*(q0*q1 + q2*q3), 1 - 2*(q1**2 + q2**2)) * 57.2958
                pitch = np.arcsin(np.clip(2*(q0*q2 - q3*q1), -1.0, 1.0)) * 57.2958
                yaw = np.arctan2(2*(q0*q3 + q1*q2), 1 - 2*(q2**2 + q3**2)) * 57.2958
                
                topic.dataframe = df.with_columns([
                    pl.Series("roll_sp_euler", roll), pl.Series("pitch_sp_euler", pitch), pl.Series("yaw_sp_euler", yaw)
                ])
                for s in ["roll_sp_euler", "pitch_sp_euler", "yaw_sp_euler"]: topic.signals[s] = None

        # 2. Altitude (NED Z -> Up [m])
        if "vehicle_local_position_0" in dataset.topics:
            topic = dataset.topics["vehicle_local_position_0"]
            df = topic.dataframe
            if "z" in df.columns:
                topic.dataframe = df.with_columns(pl.Series("alt_up", -df["z"].to_numpy()))
                topic.signals["alt_up"] = None

        if "vehicle_local_position_setpoint_0" in dataset.topics:
            topic = dataset.topics["vehicle_local_position_setpoint_0"]
            df = topic.dataframe
            if "z" in df.columns:
                topic.dataframe = df.with_columns(pl.Series("alt_sp_up", -df["z"].to_numpy()))
                topic.signals["alt_sp_up"] = None

        # 3. Ground Speed (sqrt(vx^2 + vy^2) [m/s])
        if "vehicle_local_position_0" in dataset.topics:
            topic = dataset.topics["vehicle_local_position_0"]
            df = topic.dataframe
            if "vx" in df.columns and "vy" in df.columns:
                vx, vy = df["vx"].to_numpy(), df["vy"].to_numpy()
                gs = np.sqrt(vx**2 + vy**2)
                topic.dataframe = df.with_columns(pl.Series("ground_speed_mag", gs))
                topic.signals["ground_speed_mag"] = None

    @staticmethod
    def compute_fft(time_sec, data):
        """
        시간 도메인 데이터를 Hanning Window 적용 후 주파수 도메인(FFT)으로 변환합니다.
        반환값: (frequency_array, amplitude_array)
        """
        valid_idx = ~np.isnan(data)
        t = time_sec[valid_idx]
        y = data[valid_idx]
        
        if len(t) < 2: return np.array([]), np.array([])
        
        # 평균 샘플링 주기 계산
        dt = np.mean(np.diff(t))
        if dt <= 0: return np.array([]), np.array([])
        
        N = len(y)
        # 누설 오차 방지를 위한 Hanning Window
        window = np.hanning(N)
        y_windowed = y * window
        
        yf = np.fft.fft(y_windowed)
        xf = np.fft.fftfreq(N, d=dt)
        
        # 양의 주파수 영역만 추출하여 진폭 보정
        idx = np.where(xf >= 0)
        amp = 2.0 / N * np.abs(yf[idx])
        
        return xf[idx], amp