from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import numpy as np
import io
import requests

app = FastAPI(openapi_version="3.0.2")

class FileInput(BaseModel):
    file_url: str  # 扣子会把用户上传的 CSV 变成一个 URL 传过来

# ... (前面的 import 保持不变) ...

@app.post("/analyze_patent")
async def analyze_patent(input: FileInput):
    try:
        # 1. 下载文件
        response = requests.get(input.file_url)
        response.raise_for_status()
        content = response.content
        
        # 2. 【核心修改】专读 Excel (.xlsx)
        # engine='openpyxl' 是专门读 xlsx 的引擎
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except Exception as read_err:
            return {"error": f"Excel读取失败，请确保上传的是.xlsx格式。错误信息: {str(read_err)}"}

        # --- 下面的统计逻辑完全不用动 ---
        # (为了防止你复制错，我把核心统计逻辑再贴一遍)
        
        total = len(df)
        patent_types = df['专利类型'].astype(str) if '专利类型' in df.columns else pd.Series()
        
        stats = {
            "total": total,
            "invention": int(patent_types.str.contains("发明").sum()),
            "utility": int(patent_types.str.contains("实用新型").sum()),
            "design": int(patent_types.str.contains("外观设计").sum()),
            "foreign": int(len(df[~df['公开国别'].astype(str).str.contains("中国")])) if '公开国别' in df.columns else 0
        }
        stats['other'] = total - (stats['invention'] + stats['utility'] + stats['design'])

        ipc_data = []
        if 'IPC主分类-部' in df.columns and 'IPC主分类-部(释义)' in df.columns:
            ipc_counts = df.groupby(['IPC主分类-部', 'IPC主分类-部(释义)']).size().reset_index(name='count')
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False).head(10)
            ipc_data = ipc_counts.to_dict(orient='records')

        high_value_data = []
        if '合享价值度' in df.columns:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            high_value_df = df[df['score_num'] >= 9].copy()
            if '新兴产业分类' in df.columns:
                high_value_df = high_value_df.sort_values(by='新兴产业分类')
            cols_needed = ['标题 (中文)', '申请人', '公开（公告）号', '新兴产业分类', '合享价值度']
            available_cols = [c for c in cols_needed if c in df.columns]
            high_value_data = high_value_df[available_cols].head(20).to_dict(orient='records')

        transfer_data = []
        if '受让人' in df.columns:
            transfer_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            cols_needed_t = ['标题 (中文)', '申请人', '受让人', '当前法律状态', '公开（公告）日']
            available_cols_t = [c for c in cols_needed_t if c in df.columns]
            transfer_data = transfer_df[available_cols_t].head(20).to_dict(orient='records')
            
        # 调试用：把读取到的列名返回给你，万一全是0，看看列名是不是错了
        columns_found = df.columns.tolist()

        return {
            "message": "success",
            "debug_columns": columns_found, 
            "stats": stats,
            "ipc_data": ipc_data,
            "high_value_data": high_value_data,
            "high_value_count": len(high_value_data),
            "transfer_data": transfer_data
        }

    except Exception as e:
        return {"error": str(e)}
