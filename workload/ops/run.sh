#!/bin/bash

# aiperf profile   --model RedHatAI/SmolLM-1.7B-Instruct-quantized.w8a16   --url http://localhost:8080/smollm   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer RedHatAI/SmolLM-1.7B-Instruct-quantized.w8a16 --profile-export-prefix='Exclusive' --export-level='raw' &
# wait
# aiperf profile   --model Qwen/Qwen2.5-1.5B-Instruct   --url http://localhost:8080/qwen3   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer Qwen/Qwen2.5-1.5B-Instruct  --profile-export-prefix='Exclusive' --export-level='raw' &
# wait
# aiperf profile   --model Qwen/Qwen2.5-3B-Instruct-GPTQ-Int8   --url http://localhost:8080/qwen25   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer Qwen/Qwen2.5-3B-Instruct-GPTQ-Int8 --profile-export-prefix='Exclusive' --export-level='raw' &
# wait
# aiperf profile   --model RedHatAI/gemma-2-2b-it-quantized.w4a16   --url http://localhost:8080/gemma   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer RedHatAI/gemma-2-2b-it-quantized.w4a16 --profile-export-prefix='Exclusive' --export-level='raw' &
# wait


# aiperf profile   --model RedHatAI/SmolLM-1.7B-Instruct-quantized.w8a16   --url http://localhost:8080/smollm   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer RedHatAI/SmolLM-1.7B-Instruct-quantized.w8a16 --profile-export-prefix='Concurrent' --export-level='raw' &

aiperf profile   --model Qwen/Qwen2.5-1.5B-Instruct   --url http://localhost:8080/qwen3   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer Qwen/Qwen2.5-1.5B-Instruct  --profile-export-prefix='Concurrent_(qwen3&qwen25)' --export-level='raw' &

aiperf profile   --model Qwen/Qwen2.5-3B-Instruct-GPTQ-Int8   --url http://localhost:8080/qwen25   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer Qwen/Qwen2.5-3B-Instruct-GPTQ-Int8 --profile-export-prefix='Concurrent_(qwen3&qwen25)' --export-level='raw' &

# aiperf profile   --model RedHatAI/gemma-2-2b-it-quantized.w4a16   --url http://localhost:8080/gemma   --endpoint-type chat   --streaming   --request-rate 10   --request-count 200   --tokenizer RedHatAI/gemma-2-2b-it-quantized.w4a16 --profile-export-prefix='Concurrent' --export-level='raw' &
wait
