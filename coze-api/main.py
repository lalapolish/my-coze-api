from fastapi import FastAPI
from pydantic import BaseModel
import pandas as pd
import numpy as np
import io
import requests
import matplotlib.pyplot as plt
from matplotlib import font_manager
from wordcloud import WordCloud
import base64
import traceback
import os

app = FastAPI(openapi_version="3.0.2")

# ==========================================
# 🕵️‍♂️ 侦探模式：寻找字体文件
# ==========================================
def find_font():
    try:
        # 1. 打印当前目录下所有的文件 (请在 Render Logs 里看这一行！)
        files = os.listdir('.')
        print(f">>> [DEBUG] 目录下的文件清单: {files}")
        
        # 2. 忽略大小写，寻找 simhei.ttf
        for f in files:
            if f.lower() == 'simhei.ttf':
                print(f">>> ✅ 找到字体文件: {f}")
                return f
                
    except Exception as e:
        print(f">>> 搜索字体出错: {e}")
    
    print(">>> ⚠️ 未找到 SimHei 字体，将使用默认字体 (中文可能乱码)")
    return None

# 获取字体路径
FONT_FILE = find_font()

# 配置 Matplotlib
if FONT_FILE:
    try:
        font_manager.fontManager.addfont(FONT_FILE)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=FONT_FILE).get_name()
    except:
        plt.rcParams['font.family'] = 'sans-serif'
else:
    plt.rcParams['font.family'] = 'sans-serif'

plt.rcParams['axes.unicode_minus'] = False 
PLOT_DPI = 75 

class FileInput(BaseModel):
    file_url: str

def plot_to_base64(fig):
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', dpi=PLOT_DPI)
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
        return f"data:image/png;base64,{img_base64}"
    except Exception:
        return ""

@app.post("/analyze_patent")
async def analyze_patent(input: FileInput):
    print(f">>> [Patent] Processing: {input.file_url}")
    return await process_data(input.file_url, mode="table_only")

@app.post("/analyze_visual")
async def analyze_visual(input: FileInput):
    print(f">>> [Visual] Processing: {input.file_url}")
    return await process_data(input.file_url, mode="with_visual")

async def process_data(file_url, mode):
    try:
        response = requests.get(file_url)
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
            return {"report_part1": "❌ 读取失败", "report_part2": "", "report_part3": ""}

        df.columns = df.columns.astype(str).str.strip()
        cols = df.columns.tolist()
        total = len(df)

        # 1. 基础统计
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

        # 2. IPC & 饼图
        ipc_rows = []
        ipc_pie_img = ""
        if 'IPC主分类-部' in cols:
            group_cols = ['IPC主分类-部']
            if 'IPC主分类-部(释义)' in cols:
                group_cols.append('IPC主分类-部(释义)')
            ipc_counts = df.groupby(group_cols).size().reset_index(name='count')
            ipc_counts['percent_num'] = (ipc_counts['count'] / total * 100)
            ipc_counts['percent_str'] = ipc_counts['percent_num'].round(2).astype(str) + '%'
            ipc_counts = ipc_counts.sort_values(by='count', ascending=False)
            
            for _, row in ipc_counts.iterrows():
                sec = row['IPC主分类-部']
                desc = row['IPC主分类-部(释义)'] if 'IPC主分类-部(释义)' in cols else ""
                ipc_rows.append([sec, desc, row['count'], row['percent_str']])
            
            if mode == "with_visual":
                try:
                    fig, ax = plt.subplots(figsize=(4, 4))
                    labels = []
                    for i, row in ipc_counts.iterrows():
                        label = str(row['IPC主分类-部'])
                        if 'IPC主分类-部(释义)' in cols:
                            label += f": {str(row['IPC主分类-部(释义)'])}"
                        labels.append(label)
                    
                    ax.pie(ipc_counts['count'], labels=labels, autopct='%1.1f%%', startangle=90)
                    ax.set_title('IPC 主分类分布占比', fontsize=10)
                    ipc_pie_img = plot_to_base64(fig)
                except Exception as e:
                    print(f"Pie Error: {e}")
                    pass

        # 3. 发明人 & 词云
        inv_rows = []
        inv_cloud_img = ""
        if '发明人' in cols:
            temp_inv = df['发明人'].astype(str).str.replace('，', ';').str.replace(',', ';')
            inv_exploded = temp_inv.str.split(';').explode().str.strip()
            inv_exploded = inv_exploded[(inv_exploded.notna()) & (inv_exploded != '') & (inv_exploded != 'nan')]
            inv_counts = inv_exploded.value_counts().reset_index()
            inv_counts.columns = ['name', 'count']
            
            for i, row in inv_counts.head(20).iterrows():
                inv_rows.append([row['name'], row['count']])
            
            if mode == "with_visual":
                try:
                    inv_freq_dict = inv_exploded.value_counts().to_dict()
                    if inv_freq_dict:
                        # === 🛡️ 安全词云逻辑 ===
                        # 如果找到了字体文件，就用它；否则不传 font_path 参数（用默认英文）
                        if FONT_FILE and os.path.exists(FONT_FILE):
                            wc = WordCloud(font_path=FONT_FILE, width=500, height=300, background_color='white')
                        else:
                            print(">>> ⚠️ WordCloud 降级模式：未使用中文字体")
                            wc = WordCloud(width=500, height=300, background_color='white')
                        
                        wc.generate_from_frequencies(inv_freq_dict)
                        fig_cloud, ax_cloud = plt.subplots(figsize=(5, 3))
                        ax_cloud.imshow(wc, interpolation='bilinear')
                        ax_cloud.axis('off')
                        ax_cloud.set_title('主要发明人词云', fontsize=10)
                        inv_cloud_img = plot_to_base64(fig_cloud)
                except Exception as e:
                    print(f"Cloud Error: {e}")
                    inv_cloud_img = f"*(词云生成出错: {e})*"

        # 4. 高价值
        hv_rows = []
        if '合享价值度' in cols:
            df['score_num'] = pd.to_numeric(df['合享价值度'], errors='coerce').fillna(0)
            hv_df = df[(df['score_num'] >= 9) & (df['专利类型'].astype(str).str.contains("授权"))].copy()
            if '新兴产业分类' in cols and not hv_df.empty:
                hv_df['temp_industry'] = hv_df['新兴产业分类'].astype(str).str.replace(';', ',').str.replace('，', ',')
                hv_df['temp_industry_list'] = hv_df['temp_industry'].str.split(',')
                hv_exploded = hv_df.explode('temp_industry_list')
                hv_exploded['single_industry'] = hv_exploded['temp_industry_list'].str.strip()
                hv_exploded = hv_exploded[(hv_exploded['single_industry'].notna()) & (hv_exploded['single_industry'] != '') & (hv_exploded['single_industry'] != 'nan')]
                ind_counts = hv_exploded['single_industry'].value_counts()
                hv_exploded['industry_fmt'] = hv_exploded['single_industry'].apply(lambda x: f"{x} ({ind_counts.get(x, 0)}件)")
                hv_exploded = hv_exploded.sort_values(by=['industry_fmt', '公开（公告）号'], ascending=[True, False])
                target_map = {'公开号': '公开（公告）号', '标题': '标题 (中文)', '发明人': '发明人'}
                for _, row in hv_exploded.iterrows():
                    vals = [row['industry_fmt']]
                    for k, v in target_map.items():
                        vals.append(str(row.get(v, "")) if pd.notna(row.get(v)) else "")
                    hv_rows.append(vals)

        # 5. 转让
        tf_rows = []
        if '受让人' in cols:
            tf_df = df[df['受让人'].notna() & (df['受让人'].astype(str).str.len() > 1)]
            for _, row in tf_df.iterrows():
                tf_rows.append([
                    str(row.get('公开（公告）号', "")),
                    str(row.get('标题 (中文)', "")),
                    str(row.get('发明人', "")),
                    str(row.get('受让人', ""))
                ])

        # === 拼接 Markdown ===
        md1 = "### 1. 专利概况\n| 指标 | 数量 |\n| :--- | :--- |\n"
        md1 += f"| 申请总量 | {total} |\n| 发明授权 | {inv_auth} |\n| 发明申请 | {inv_app} |\n"
        md1 += f"| 实用新型 | {utility} |\n| 外观设计 | {design} |\n| 外国专利 | {foreign} |\n\n"
        md1 += "### 2. IPC 主分类分布\n| 序号 | IPC部 | 释义 | 数量 | 占比 |\n| :--- | :--- | :--- | :--- | :--- |\n"
        for i, r in enumerate(ipc_rows, 1):
            md1 += f"| {i} | {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"
        
        if mode == "with_visual" and ipc_pie_img:
            md1 += f"\n\n#### IPC分布可视化\n![]({ipc_pie_img})\n"

        md2 = "### 3. 主要发明人 (Top 20)\n| 发明人 | 发明频率 |\n| :--- | :--- |\n"
        if not inv_rows: md2 += "| 暂无数据 | 0 |\n"
        else:
            for r in inv_rows: md2 += f"| {r[0]} | {r[1]} |\n"
        
        if mode == "with_visual" and inv_cloud_img:
            md2 += f"\n\n#### 发明人词云\n![]({inv_cloud_img})\n"

        md2 += "\n### 4. 高价值授权专利推荐 (>=9分)\n| 新兴产业分类 | 公开号 | 标题 | 发明人 |\n| :--- | :--- | :--- | :--- |\n"
        if not hv_rows: md2 += "| 暂无符合条件的授权专利 | - | - | - |\n"
        else:
            for r in hv_rows: md2 += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        md3 = "### 5. 专利转让情况\n| 公开号 | 标题 | 发明人 | 受让人 |\n| :--- | :--- | :--- | :--- |\n"
        for r in tf_rows:
            md3 += f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n"

        return {"report_part1": md1, "report_part2": md2, "report_part3": md3}

    except Exception as e:
        traceback.print_exc()
        return {"report_part1": f"❌ 处理出错: {str(e)}", "report_part2": "", "report_part3": ""}
