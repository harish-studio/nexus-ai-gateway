import os
os.environ['FASTEMBED_CACHE_DIR'] = '/root/.fastembed_cache'
from fastembed import TextEmbedding
list(TextEmbedding(model_name='BAAI/bge-small-en-v1.5').embed(['warmup']))
import subprocess
result = subprocess.run(['find', '/root', '-name', '*.onnx'], capture_output=True, text=True)
print('ONNX files found:')
print(result.stdout or 'NONE')
result2 = subprocess.run(['find', '/tmp', '-name', '*.onnx'], capture_output=True, text=True)
print('ONNX in /tmp:')
print(result2.stdout or 'NONE')
