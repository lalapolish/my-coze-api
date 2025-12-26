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
    print(f">>> 收到请求，开始下载文件: {input.file_url}") # 调试日志
    try:
        # 1. 下载文件
        response = requests.get(input.file_url)
        response.raise_for_status()
        content = response.content
        print(f">>> 文件下载成功，大小: {len(content)} 字节")
        
        # 2. 【万能读取逻辑】
        df = None
        error_log = []
        
        # 尝试 A: 当作 Excel (.xlsx) 读取
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
            print(">>> 成功以 Excel 格式读取")
        except Exception as e:
            error_log.append(f"Excel读取失败({str(e)})")
            print(f">>> Excel 读取失败，尝试切换为 CSV...")
            
            # 尝试 B: 当作 CSV (utf-8) 读取
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
                print(">>> 成功以 CSV (utf-8) 格式读取")
            except Exception as e_utf8:
                error_log.append(f"CSV-utf8失败({str(e_utf8)})")
                
                # 尝试 C: 当作 CSV (gbk) 读取
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding='gbk')
                    print(">>> 成功以 CSV (gbk) 格式读取")
                except Exception as e_gbk:
                    error_log.append(f"CSV-gbk失败({str(e_gbk)})")
        
        if df is None:
            # 如果都失败了，返回详细错误给 Bot，让它告诉你原因
            return {"error": f"文件读取全军覆没。详细日志: {'; '.join(error_log)}"}

        # 3. 开始统计 (基于你提供的真实表头)
        cols = df.columns.tolist()
        total = len(df)
        
        # 初始化
        invention = utility = design = foreign = 0
        
        # 统计专利类型
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            invention = int(pt.str.contains("发明").sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
            
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

        # IPC 分布
        ipc_data = []
        if 'IPC主分类-部' in cols and 'IPC主分类-部(释义)' in cols:
            ipc_counts = df.groupby(['IPC主分类-部', 'IPC主分类-部(释义)']).size().reset_index(name='count')
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False).head(10)
            ipc_data = ipc_counts.to_dict(orient='records')

        # 高价值专利
        high_value_data = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            high_value_df = df[df['score_num'] >= 9].copy()
            target_cols = ['标题 (中文)', '申请人', '公开（公告）号', '新兴产业分类', '合享价值度']
            final_cols = [c for c in target_cols if c in cols]
            high_value_data = high_value_df[final_cols].head(20).to_dict(orient='records')

        # 专利转让
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
        print(">>> 分析完成，准备返回结果")
        return result

    except Exception as e:
        print(f">>> 发生严重错误: {str(e)}")
        return {"error": str(e)}
