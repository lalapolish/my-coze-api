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
        
        # 2. 强制使用 Excel 读取 (engine='openpyxl')
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except Exception as e:
            return {"error": f"读取失败，请确认上传的是 .xlsx 文件。错误: {str(e)}"}

        # 3. 开始统计 (完全对应你的表格要求)
        total = len(df)
        
        # 容错：防止列名不对，先获取所有列名
        cols = df.columns.tolist()
        
        # 统计变量初始化
        invention = 0
        utility = 0
        design = 0
        foreign = 0
        
        # 任务一：专利概况逻辑
        if '专利类型' in cols:
            # 转成字符串防止报错
            pt = df['专利类型'].astype(str)
            invention = int(pt.str.contains("发明").sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
        
        if '公开国别' in cols:
            country = df['公开国别'].astype(str)
            # 统计不包含"中国"的
            foreign = int(len(df[~country.str.contains("中国")]))

        stats = {
            "total": total,
            "invention": invention,
            "utility": utility,
            "design": design,
            "foreign": foreign,
            "other": total - (invention + utility + design)
        }

        # 任务二：IPC 分布
        ipc_data = []
        if 'IPC主分类-部' in cols and 'IPC主分类-部(释义)' in cols:
            ipc_counts = df.groupby(['IPC主分类-部', 'IPC主分类-部(释义)']).size().reset_index(name='count')
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False).head(10)
            ipc_data = ipc_counts.to_dict(orient='records')

        # 任务三：高价值专利 (>=9)
        high_value_data = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            high_value_df = df[df['score_num'] >= 9].copy()
            
            output_cols = ['标题 (中文)', '申请人', '公开（公告）号', '新兴产业分类', '合享价值度']
            # 只选存在的列
            final_cols = [c for c in output_cols if c in cols]
            
            if '新兴产业分类' in cols:
                high_value_df = high_value_df.sort_values(by='新兴产业分类')
                
            high_value_data = high_value_df[final_cols].head(20).to_dict(orient='records')

        # 任务四：转让情况
        transfer_data = []
        if '受让人' in cols:
            transfer_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            t_cols = ['标题 (中文)', '申请人', '受让人', '当前法律状态', '公开（公告）日']
            final_t_cols = [c for c in t_cols if c in cols]
            transfer_data = transfer_df[final_t_cols].head(20).to_dict(orient='records')

        return {
            "message": "success",
            "debug_columns": cols, # 调试用：把读到的列名还给你
            "stats": stats,
            "ipc_data": ipc_data,
            "high_value_data": high_value_data,
            "high_value_count": len(high_value_data),
            "transfer_data": transfer_data
        }

    except Exception as e:
        return {"error": str(e)}
