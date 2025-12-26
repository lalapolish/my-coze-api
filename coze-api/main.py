from fastapi import FastAPI
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
    print(f">>> [Dynamic] 开始处理文件: {input.file_url}")
    try:
        # 1. 下载文件
        response = requests.get(input.file_url)
        content = response.content
        
        # 2. 动态读取 (Excel优先，CSV兜底)
        df = None
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except:
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
            except:
                df = pd.read_csv(io.BytesIO(content), encoding='gbk')

        if df is None:
            return {"error": "读取失败"}

        # 3. 清洗列名 (去空格，防止 '专利类型 ' 这种坑)
        df.columns = df.columns.astype(str).str.strip()
        cols = df.columns.tolist()
        total = len(df) # 动态获取当前文件的总行数

        # -------------------------------------------------------
        # 逻辑 1: 专利概况 (发明授权/申请 + 动态统计)
        # -------------------------------------------------------
        inv_auth = inv_app = utility = design = foreign = 0
        
        # A. 统计外国专利 (按公开国别)
        if '公开国别' in cols:
            country = df['公开国别'].astype(str)
            # 只要不是"中国"，都算外国
            foreign = int(len(df[~country.str.contains("中国")]))

        # B. 统计类型 (发明授权 vs 申请)
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            # 这里的逻辑对任何季度通用：
            # 1. 必须包含"发明"
            # 2. 如果包含"授权" -> 发明授权
            # 3. 如果不含"授权" -> 发明申请
            inv_auth = int(pt.apply(lambda x: '发明' in x and '授权' in x).sum())
            inv_app = int(pt.apply(lambda x: '发明' in x and '授权' not in x).sum())
            
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())

        stats = {
            "total": total,
            "inv_auth": inv_auth,
            "inv_app": inv_app,
            "utility": utility,
            "design": design,
            "foreign": foreign
        }

        # -------------------------------------------------------
        # 逻辑 2: IPC 分布 (全量输出 + 百分比)
        # -------------------------------------------------------
        ipc_data = []
        if 'IPC主分类-部' in cols:
            group_cols = ['IPC主分类-部']
            # 如果有释义列就带上，没有就不带
            if 'IPC主分类-部(释义)' in cols:
                group_cols.append('IPC主分类-部(释义)')
            
            # 1. 分组统计
            ipc_counts = df.groupby(group_cols).size().reset_index(name='count')
            
            # 2. 计算占比 (当前数量 / 当前总数)
            ipc_counts['percent'] = (ipc_counts['count'] / total * 100).round(2).astype(str) + '%'
            
            # 3. 排序 (数量多的在前)
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False)
            
            # 4. 字段标准化 (方便前端展示)
            rename_map = {
                'IPC主分类-部': 'section',
                'IPC主分类-部(释义)': 'desc',
                'count': 'count',
                'percent': 'percent'
            }
            ipc_counts = ipc_counts.rename(columns=rename_map)
            
            # 5. 输出所有数据 (不截断 Top10)
            safe_cols = [c for c in ['section', 'desc', 'count', 'percent'] if c in ipc_counts.columns]
            ipc_data = ipc_counts[safe_cols].to_dict(orient='records')

        # -------------------------------------------------------
        # 逻辑 3: 高价值专利 (>=9分, 产业聚合排序)
        # -------------------------------------------------------
        high_value_data = []
        if '合享价值度' in cols:
            # 数字化处理
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            # 筛选 >= 9
            hv_df = df[df['score_num'] >= 9].copy()
            
            if '新兴产业分类' in cols:
                # 统计各产业数量
                industry_counts = hv_df['新兴产业分类'].value_counts()
                
                # 定义格式化函数：把 "新一代信息技术" 变成 "新一代信息技术 (6件)"
                def format_industry(name):
                    c = industry_counts.get(name, 0)
                    return f"{name} ({c}件)"
                
                # 应用格式化
                hv_df['新兴产业分类'] = hv_df['新兴产业分类'].apply(format_industry)
                # 排序：把相同产业的排在一起
                hv_df = hv_df.sort_values(by='新兴产业分类', ascending=False)

            # 字段映射
            hv_map = {
                '新兴产业分类': 'industry', # 已经带了 (x件) 后缀
                '公开（公告）号': 'pub_number',
                '标题 (中文)': 'title',
                '发明人': 'inventor'
            }
            
            records = []
            for _, row in hv_df.iterrows():
                item = {}
                for ch, en in hv_map.items():
                    if ch in cols:
                        val = row[ch]
                        # 处理空值
                        item[en] = str(val) if pd.notna(val) else ""
                if item:
                    records.append(item)
            high_value_data = records

        # -------------------------------------------------------
        # 逻辑 4: 转让情况 (受让人不为空)
        # -------------------------------------------------------
        transfer_data = []
        if '受让人' in cols:
            # 筛选：受让人不为空 且 长度>1
            tf_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)].copy()
            
            # 字段映射
            tf_map = {
                '公开（公告）号': 'pub_number',
                '标题 (中文)': 'title',
                '发明人': 'inventor',
                '受让人': 'assignee'
            }
            
            t_records = []
            for _, row in tf_df.iterrows():
                item = {}
                for ch, en in tf_map.items():
                    if ch in cols:
                        val = row[ch]
                        item[en] = str(val) if pd.notna(val) else ""
                if item:
                    t_records.append(item)
            transfer_data = t_records

        result = {
            "message": "success",
            "stats": stats,
            "ipc_data": ipc_data,
            "high_value_data": high_value_data,
            "transfer_data": transfer_data
        }
        print(f">>> 计算完成! Stats: {stats}")
        return result

    except Exception as e:
        print(f"Error: {str(e)}")
        return {"error": str(e)}
