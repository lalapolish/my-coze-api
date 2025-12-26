from fastapi import FastAPI
from pydantic import BaseModel
import pandas as pd
import numpy as np

# 初始化应用
# 强制使用 3.0.2 版本，这样扣子就能读懂了
app = FastAPI(openapi_version="3.0.2")


# 定义扣子传给我们的数据格式
class DataInput(BaseModel):
    numbers: list[float]  # 这是一个数字列表


# 这是一个 API 接口，路径是 /analyze
@app.post("/analyze")
async def analyze_data(item: DataInput):
    # --- 这里开始可以使用扣子没有的库 ---

    # 1. 把数据转成 Pandas DataFrame
    df = pd.DataFrame(item.numbers, columns=['Value'])

    # 2. 计算一些统计数据
    result = {
        "mean": df['Value'].mean(),  # 平均值
        "max": df['Value'].max(),  # 最大值
        "std_dev": df['Value'].std(),  # 标准差
        "message": "数据分析完成，由外部 Python 服务处理"
    }

    # 3. 返回结果给扣子
    return result


# 这是一个测试接口，看看服务活着没
@app.get("/")
def read_root():
    return {"status": "Service is running!"}
