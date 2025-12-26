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
    try:
        # 1. 下载文件
        response = requests.get(input.file_url)
        response.raise_for_status()
        content = response.content
        
        # 2. 【核心修改】智能读取：先试 Excel，失败则试 CSV
        df = None
        read_error = ""
        
        # 尝试 A: 当做 Excel 读取
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except Exception as e_excel:
            read_error += f"Excel读取失败: {str(e_excel)}; "
            # 尝试 B: 当做 UTF-8 CSV 读取
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
            except Exception as e_csv_utf8:
                read_error += f"CSV(utf-8)读取失败: {str(e_csv_utf8)}; "
                # 尝试 C: 当做 GBK CSV 读取
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding='gbk')
                except Exception as e_csv_gbk:
                    return {"error": f"文件格式无法识别，请确保是 .xlsx 或 .csv。详细错误: {read_error}"}

        # 3. 开始统计
        cols = df.columns.tolist()
        total = len(df)
        
        # --- 任务一：专利概况 ---
        invention = utility = design = foreign = 0
        
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            invention = int(pt.str.contains("发明").sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
            
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

        # --- 任务二：IPC 分布 ---
        ipc_data = []
        if 'IPC主分类-部' in cols and 'IPC主分类-部(释义)' in cols:
            ipc_counts = df.groupby(['IPC主分类-部', 'IPC主分类-部(释义)']).size().reset_index(name='count')
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False).head(10)
            ipc_data = ipc_counts.to_dict(orient='records')

        # --- 任务三：高价值专利 (>=9) ---
        high_value_data = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            high_value_df = df[df['score_num'] >= 9].copy()
            
            target_cols = ['标题 (中文)', '申请人', '公开（公告）号', '新兴产业分类', '合享价值度']
            final_cols = [c for c in target_cols if c in cols]
            
            if '新兴产业分类' in cols:
                high_value_df = high_value_df.sort_values(by='新兴产业分类')
                
            high_value_data = high_value_df[final_cols].head(20).to_dict(orient='records')

        # --- 任务四：专利转让情况 ---
        transfer_data = []
        if '受让人' in cols:
            # 筛选：受让人不为空，且长度大于1
            transfer_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            
            t_cols = ['标题 (中文)', '申请人', '受让人', '公开（公告）日']
            final_t_cols = [c for c in t_cols if c in cols]
            
            transfer_data = transfer_df[final_t_cols].head(20).to_dict(orient='records')

        return {
            "message": "success",
            "debug_columns": cols,
            "stats": stats,
            "ipc_data": ipc_data,
            "high_value_data": high_value_data,
            "high_value_count": len(high_value_data),
            "transfer_data": transfer_data
        }

    except Exception as e:
        return {"error": str(e)}
