FROM ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlex/paddlex:paddlex3.0.1-paddlepaddle3.0.0-cpu

WORKDIR /root/PaddleX/paddlex

# 安装 hpi-cpu，如您所指示
RUN paddlex --install hpi-cpu
RUN paddlex --install serving
RUN python -m pip install --no-cache-dir "paddlex[ocr]==3.0.1"

COPY docker/PP-StructureV3.yaml /root/PaddleX/paddlex/PP-StructureV3.yaml

# 暴露 PaddleX 服务端口
EXPOSE 8080

# 运行 PaddleX PP-StructureV3 流水线服务（强制 CPU）
CMD ["paddlex", "--serve", "--pipeline", "PP-StructureV3.yaml", "--host", "0.0.0.0", "--port", "8080", "--device", "cpu"]