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
    print(f">>> [Split-Industry] 开始处理: {input.file_url}")
    try:
        # 1. 下载与读取
        response = requests.get(input.file_url)
        content = response.content
        
        df = None
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except:
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
            except:
                df = pd.read_csv(io.BytesIO(content), encoding='gbk')

        if df is None:
            return {"markdown_report": "❌ 文件读取失败"}

        # 清洗列名
        df.columns = df.columns.astype(str).str.strip()
        cols = df.columns.tolist()
        total = len(df)

        # ==================== 1. 基础统计 ====================
        inv_auth = inv_app = utility = design = foreign = 0
        if '专利类型' in cols:
            pt = df['专利类型'].astype(str)
            inv_auth = int(pt.apply(lambda x: '发明' in x and '授权' in x).sum())
            inv_app = int(pt.apply(lambda x: '发明' in x and '授权' not in x).sum())
            utility = int(pt.str.contains("实用新型").sum())
            design = int(pt.str.contains("外观设计").sum())
        if '公开国别' in cols:
            country = df['公开国别'].astype(str)
            foreign = int(len(df[~country.str.contains("中国")]))

        # ==================== 2. IPC 分布 ====================
        ipc_rows = []
        if 'IPC主分类-部' in cols:
            group_cols = ['IPC主分类-部']
            if 'IPC主分类-部(释义)' in cols:
                group_cols.append('IPC主分类-部(释义)')
            
            ipc_counts = df.groupby(group_cols).size().reset_index(name='count')
            ipc_counts['percent'] = (ipc_counts['count'] / total * 100).round(2).astype(str) + '%'
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False)
            
            for _, row in ipc_counts.iterrows():
                sec = row['IPC主分类-部']
                desc = row['IPC主分类-部(释义)'] if 'IPC主分类-部(释义)' in cols else ""
                ipc_rows.append([sec, desc, row['count'], row['percent']])

        # ==================== 3. 高价值 (核心修改：支持多分类拆分) ====================
        hv_rows = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            # 筛选 >= 9
            hv_df = df[df['score_num'] >= 9].copy()
            
            if '新兴产业分类' in cols and not hv_df.empty:
                # A. 预处理：把中文逗号、分号都换成英文逗号，方便统一拆分
                # 比如: "9.1 (xx); 1.4 (yy)" -> "9.1 (xx), 1.4 (yy)"
                hv_df['temp_industry'] = hv_df['新兴产业分类'].astype(str).str.replace(';', ',').str.replace('，', ',')
                
                # B. 拆分 (Split) 成列表
                hv_df['temp_industry_list'] = hv_df['temp_industry'].str.split(',')
                
                # C. 炸裂 (Explode): 一行变多行！
                # 如果一个专利有3个分类，这里就会变成3行，确保每个分类都能统计到
                hv_exploded = hv_df.explode('temp_industry_list')
                
                # D. 清洗: 去除空格，过滤空值
                hv_exploded['single_industry'] = hv_exploded['temp_industry_list'].str.strip()
                hv_exploded = hv_exploded[
                    (hv_exploded['single_industry'].notna()) & 
                    (hv_exploded['single_industry'] != '') & 
                    (hv_exploded['single_industry'] != 'nan')
                ]
                
                # E. 统计拆分后的数量
                ind_counts = hv_exploded['single_industry'].value_counts()
                
                # F. 格式化名称: "产业名 (N件)"
                hv_exploded['industry_fmt'] = hv_exploded['single_industry'].apply(
                    lambda x: f"{x} ({ind_counts.get(x, 0)}件)"
                )
                
                # G. 排序: 先按产业名聚类，再按公开号排序
                hv_exploded = hv_exploded.sort_values(by=['industry_fmt', '公开（公告）号'], ascending=[True, False])
                
                # H. 提取输出数据
                # 注意：这里我们取 hv_exploded (炸裂后的表)
                target_map = {
                    '公开号': '公开（公告）号',
                    '标题': '标题 (中文)',
                    '发明人': '发明人'
                }
                
                for _, row in hv_exploded.iterrows():
                    vals = []
                    # 第一列：带数量的产业名
                    vals.append(row['industry_fmt'])
                    
                    # 后续列
                    for k, v in target_map.items():
                        if v in cols:
                            val = str(row.get(v, "")) if pd.notna(row.get(v)) else ""
                            vals.append(val)
                        else:
                            vals.append("")
                    hv_rows.append(vals)

        # ==================== 4. 转让情况 ====================
        tf_rows = []
        if '受让人' in cols:
            tf_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            t_targets = ['公开（公告）号', '标题 (中文)', '发明人', '受让人']
            for _, row in tf_df.iterrows():
                vals = []
                for t in t_targets:
                    val = str(row.get(t, "")) if pd.notna(row.get(t, "")) else ""
                    vals.append(val)
                tf_rows.append(vals)

        # ==================== 生成 Markdown ====================
        md = "### 1. 专利概况\n"
        md += "| 指标 | 数量 |\n| :--- | :--- |\n"
        md += f"| 申请总量 | {total} |\n"
        md += f"| 发明授权 | {inv_auth} |\n"
        md += f"| 发明申请 | {inv_app} |\n"
        md += f"| 实用新型 | {utility} |\n"
        md += f"| 外观设计 | {design} |\n"
        md += f"| 外国专利 | {foreign} |\n\n"

        md += "### 2. IPC 主分类分布\n"
        md += "| 序号 | IPC部 | 释义 | 数量 | 占比 |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for i, r in enumerate(ipc_rows, 1):
            md += f"| {i} | {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"
        md += "\n"

        md += "### 3. 高价值专利推荐 (>=9分)\n"
        md += "| 新兴产业分类 | 公开号 | 标题 | 发明人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in hv_rows:
            md += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"
        md += "\n"

        md += "### 4. 专利转让情况\n"
        md += "| 公开号 | 标题 | 发明人 | 受让人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in tf_rows:
            md += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        print(f">>> 报告生成完毕，长度: {len(md)}")
        return {"markdown_report": md}

    except Exception as e:
        return {"markdown_report": f"❌ 处理出错: {str(e)}"}
