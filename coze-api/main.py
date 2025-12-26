from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import numpy as np
import io
import requests

app = FastAPI(openapi_version="3.0.2")

class FileInput(BaseModel):
    file_url: str

@app.post("/analyze_patent")
async def analyze_patent(input: FileInput):
    print(f">>> [1/5] 开始下载文件: {input.file_url}")
    try:
        # 1. 下载文件
        response = requests.get(input.file_url)
        response.raise_for_status()
        content = response.content
        print(f">>> [2/5] 下载成功，大小: {len(content)} 字节")
        
        # 2. 读取文件 (Excel 优先，CSV 兜底)
        df = None
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
            print(">>> [3/5] 成功以 Excel 格式读取")
        except:
            print(">>> Excel 读取失败，尝试 CSV...")
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
            except:
                df = pd.read_csv(io.BytesIO(content), encoding='gbk')

        if df is None:
            return {"error": "文件读取失败，请检查格式"}

        # 【关键步骤】清洗列名 (去除前后空格)
        # 这能解决 "专利类型 " 和 "专利类型" 不匹配的问题
        df.columns = df.columns.astype(str).str.strip()
        cols = df.columns.tolist()
        total = len(df)
        print(f">>> [4/5] 读到的列名(已清洗): {cols}")  # 看日志这里！

        # 3. 统计逻辑
        invention = utility = design = foreign = 0
        
        # 统计专利类型
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            invention = int(pt.str.contains("发明").sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
        else:
            print("!!! 警告：未找到 '专利类型' 列")
            
        # 统计国外专利
        if '公开国别' in cols:
            country = df['公开国别'].astype(str)
            foreign = int(len(df[~country.str.contains("中国")]))

        stats = {
            "total": total,
            "invention": invention,
            "utility": utility,
            "design": design,
            "foreign": foreign,
            "other": total - (invention + utility + design)
        }
        
        # 【直接把结果打印在日志里】
        print(f">>> [计算结果] 统计数据: {stats}")

        # IPC
        ipc_data = []
        if 'IPC主分类-部' in cols and 'IPC主分类-部(释义)' in cols:
            ipc_counts = df.groupby(['IPC主分类-部', 'IPC主分类-部(释义)']).size().reset_index(name='count')
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False).head(10)
            ipc_data = ipc_counts.to_dict(orient='records')

        # 高价值
        high_value_data = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            high_value_df = df[df['score_num'] >= 9].copy()
            target_cols = ['标题 (中文)', '申请人', '公开（公告）号', '新兴产业分类', '合享价值度']
            final_cols = [c for c in target_cols if c in cols]
            if '新兴产业分类' in cols:
                high_value_df = high_value_df.sort_values(by='新兴产业分类')
            high_value_data = high_value_df[final_cols].head(20).to_dict(orient='records')

        # 转让
        transfer_data = []
        if '受让人' in cols:
            transfer_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            t_cols = ['标题 (中文)', '申请人', '受让人', '公开（公告）日']
            final_t_cols = [c for c in t_cols if c in cols]
            transfer_data = transfer_df[final_t_cols].head(20).to_dict(orient='records')

        result = {
            "message": "success",
            "debug_columns": cols,
            "stats": stats,
            "ipc_data": ipc_data,
            "high_value_data": high_value_data,
            "high_value_count": len(high_value_data),
            "transfer_data": transfer_data
        }
        print(f">>> [5/5] 准备返回 {len(high_value_data)} 条高价值数据")
        return result

    except Exception as e:
        print(f"!!! 错误: {str(e)}")
        return {"error": str(e)}
