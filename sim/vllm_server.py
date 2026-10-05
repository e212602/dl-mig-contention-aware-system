from transformers import AutoTokenizer
import pandas as pd    
import json
import matplotlib.pyplot as plt
import numpy as np
from io import StringIO


class vlllm_server:
    def __init__(self, model_name: str, path: str, prefix = None):
        self.model_name = model_name
        self.__path__ = path
        self.df_excl : pd.DataFrame = None
        self.df_conc : pd.DataFrame = None
        self.pcie_demand : float = -1
        self.base_throughput : float = -1
        self.concurrent_throughput: float = -1
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name.replace('_','/'))
        self.base_intensity = -1
        if not prefix:
            self.list_of_prefixes = ['Exclusive', 'Concurrent']
        else:
            self.list_of_prefixes = prefix

    def read_summary_report(self, prefix):
        with open(self.__path__ + prefix + ".csv", "r") as f:
            text = f.read()

        # Headers that identify each table
        headers = [
            "Metric,avg,min,max,sum,p1,p5,p10,p25,p50,p75,p90,p95,p99,std",
            "Metric,Value",
            "Endpoint,GPU_Index,GPU_Name,GPU_UUID,Platform,Metric,avg,min,max,sum,p1,p5,p10,p25,p50,p75,p90,p95,p99,std"
        ]

        # Find the starting position of each table
        positions = [text.find(header) for header in headers]

        # Check that all headers were found
        print(positions)

        # Extract each table
        parts = []

        for i, start in enumerate(positions):
            if start == -1:
                continue

            if i + 1 < len(positions) and positions[i + 1] != -1:
                end = positions[i + 1]
            else:
                end = len(text)

            parts.append(text[start:end].strip())

        # Convert to DataFrames
        # df_metrics = pd.read_csv(StringIO(parts[0]))
        df_summary = pd.read_csv(StringIO(parts[1]))
        # df_gpu = pd.read_csv(StringIO(parts[2])) 
        return df_summary


    def generate_aiperf_dataframes(self):
        for prefix, attr in zip(self.list_of_prefixes, ['df_excl', 'df_conc']):
            data = pd.read_json(self.__path__ + prefix + "_raw.jsonl", lines=True)
            assert len(data["metadata"]) == len(data["start_perf_ns"]) == len(data["request_headers"]) == len(data["status"]) == len(data["responses"]) == len(data["payload"])

            rows = []  # accumulate as list of dicts, build DataFrame once (also much faster than repeated concat)
            for i in range(len(data["responses"])):
                assert data["request_headers"][i]["X-Request-ID"] == data["metadata"][i]["x_request_id"]
                assert len(data["payload"][i]["messages"]) == 1
                row = dict(data["metadata"][i])  # copy, don't mutate the original dict in place
                row["start_perf_ns"] = data["start_perf_ns"][i]
                row["status"] = data["status"][i]
                row["role"] = data["payload"][i]["messages"][0]["role"]
                row["content"] = data["payload"][i]["messages"][0]["content"]
                row["model"] = data["payload"][i]["model"]
                row["response"] = ""

                end_perf_ns = 0
                for packets in data["responses"][i]:
                    end_perf_ns = max(end_perf_ns, packets['perf_ns'])
                    for packet in packets["packets"]:
                        if packet["value"].startswith("{"):
                            jsonObj = json.loads(packet["value"])
                            assert row["model"] == jsonObj["model"]
                            for choice in jsonObj["choices"]:
                                row["response"] += choice["delta"]["content"]

                row['end_perf_ns'] = end_perf_ns
                rows.append(row)

            setattr(self, attr, pd.DataFrame(rows))


    def compute_pcie_demand(self):
        df = pd.read_csv(self.__path__ + "Exclusive_raw_gpu.csv")
        self.pcie_demand = (df.loc[df["metric"] == "DCGM_FI_PROF_PCIE_RX_BYTES", "value"].mean() / 1024 / 1024 / 1024)


    def compute_throughput(self):
        for df_attr, out_attr in zip(['df_excl', 'df_conc'], ['base_throughput', 'concurrent_throughput']):
            df = getattr(self, df_attr)
            duration = (df['end_perf_ns'].max() - df['start_perf_ns'].min()) * 1e-9
            total_output_tokens = sum(
                len(self.tokenizer.encode(row['response'], add_special_tokens=False))
                for _, row in df.iterrows()
            )
            setattr(self, out_attr, total_output_tokens / duration)


    def analyze(self):
        self.generate_aiperf_dataframes()
        self.compute_pcie_demand()
        self.compute_throughput()
        print(f"{self.model_name}:")
        print(f"\t\tPCIe Demand: {self.pcie_demand:.2f} GB/s")
        print(f"\t\tBase Throughput: {self.base_throughput:.2f} tokens/s")
        print(f"\t\tConcurrent Throughput: {self.concurrent_throughput:.2f} tokens/s")

    def compute_intensity(self):
        if self.base_throughput > 0 and self.pcie_demand > 0:
            self.base_intensity = self.base_throughput / self.pcie_demand
        else:
            self.analyze()
            self.base_intensity = self.base_throughput / self.pcie_demand

        print(f"Intensity of {self.model_name}: {self.base_intensity:.2f} Tokens/Byte")

    def pcie_util_vs_inst_throughput(self):
        df = pd.read_csv(self.__path__ + "Exclusive_raw_gpu.csv")
        df = df.loc[df["metric"] == "DCGM_FI_PROF_PCIE_RX_BYTES", ["timestamp","value"]]
        df['timestamp'] = pd.to_datetime(df['timestamp']).astype('int64')
        df['timestamp'] = df['timestamp'] - df['timestamp'].min()

        df2 = self.df_excl.copy()
        df2['num_tokens'] = df2['response'].apply(lambda x: len(self.tokenizer.encode(x, add_special_tokens=False)))
        df2['timestamp'] = df2['start_perf_ns'] - df2['start_perf_ns'].min()
        # --- align both clocks to seconds-since-start ---
        df = df.sort_values('timestamp').reset_index(drop=True)
        df['t_sec'] = df['timestamp'] / 1e9

        # --- align clocks ---
        df = df.sort_values('timestamp').reset_index(drop=True)
        df['t_sec'] = df['timestamp'] / 1e9

        df2 = df2.sort_values('timestamp').reset_index(drop=True)
        df2['t_sec'] = df2['timestamp'] / 1e9
        df2['end_t_sec'] = df2['t_sec'] + (df2['end_perf_ns'] - df2['start_perf_ns']) * 1e-9

        # =========================================================
        # 1. Arrival rate — bin request *arrivals* using PCIe timestamps as bin edges
        # =========================================================
        bin_edges = df['t_sec'].values
        bin_labels = np.arange(len(bin_edges) - 1)

        df2['arrival_bin'] = pd.cut(df2['t_sec'], bins=bin_edges, labels=bin_labels, include_lowest=True)

        arrivals_per_bin = df2.groupby('arrival_bin', observed=True).size().reindex(bin_labels, fill_value=0)
        bin_durations = np.diff(bin_edges)
        arrival_rate = arrivals_per_bin.values / bin_durations  # requests/sec

        # also track input token arrival rate if you have input token counts (e.g. prompt length)
        # tokens_per_bin = df2.groupby('arrival_bin', observed=True)['num_input_tokens'].sum().reindex(bin_labels, fill_value=0)
        # input_token_rate = tokens_per_bin.values / bin_durations

        interval_midpoints = (bin_edges[:-1] + bin_edges[1:]) / 2

        # =========================================================
        # 2. Concurrency / queue depth (event-based sweep — fast, no O(n*m) loop)
        # =========================================================
        starts = df2['t_sec'].values
        ends = df2['end_t_sec'].values

        events = np.concatenate([
            np.column_stack([starts, np.ones_like(starts)]),
            np.column_stack([ends, -np.ones_like(ends)])
        ])
        events = events[np.argsort(events[:, 0])]
        cum_concurrency = np.cumsum(events[:, 1])
        event_times = events[:, 0]

        # sample concurrency at each PCIe timestamp
        concurrency_at_pcie = np.array([
            cum_concurrency[np.searchsorted(event_times, t, side='right') - 1] if t >= event_times[0] else 0
            for t in df['t_sec'].values
        ])
        df['concurrency'] = concurrency_at_pcie

        # =========================================================
        # PLOT: arrival rate (burstiness) / concurrency / PCIe, stacked, shared x-axis
        # =========================================================
        fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

        axes[0].bar(interval_midpoints, arrival_rate, width=bin_durations, color='tab:orange', align='center')
        axes[0].set_ylabel('Arrival rate\n(req/s)')
        axes[0].set_title('Input Burstiness (Request Arrival Rate)')

        axes[1].plot(df['t_sec'], df['concurrency'], color='tab:green', drawstyle='steps-post')
        axes[1].set_ylabel('In-flight\nrequests')
        axes[1].set_title('Concurrency / Queue Depth (post-serialization load)')

        axes[2].plot(df['t_sec'], df['value'], color='tab:blue')
        axes[2].set_ylabel('PCIe RX\nBytes')
        axes[2].set_xlabel('Time since start (s)')
        axes[2].set_title('PCIe RX Throughput')

        fig.tight_layout()
        plt.show()

        # =========================================================
        # 3. Cross-correlation: does PCIe lag the arrival bursts?
        # =========================================================
        from scipy.signal import correlate

        # resample PCIe onto the same bin grid as arrival_rate for a fair comparison
        pcie_resampled = np.interp(interval_midpoints, df['t_sec'], df['value'])

        # normalize both signals (zero mean, unit variance) so correlation reflects shape, not scale
        def normalize(x):
            return (x - np.mean(x)) / (np.std(x) + 1e-9)

        a_norm = normalize(arrival_rate)
        p_norm = normalize(pcie_resampled)

        corr = correlate(p_norm, a_norm, mode='full')
        lags = np.arange(-len(a_norm) + 1, len(a_norm)) * np.mean(bin_durations)

        best_lag = lags[np.argmax(corr)]
        print(f"PCIe response lags arrival bursts by ~{best_lag:.3f} seconds (positive = PCIe lags behind arrivals)")

        plt.figure(figsize=(10, 4))
        plt.plot(lags, corr)
        plt.axvline(0, color='gray', linestyle='--', alpha=0.5)
        plt.axvline(best_lag, color='red', linestyle='--', label=f'peak lag = {best_lag:.2f}s')
        plt.xlabel('Lag (s)')
        plt.ylabel('Cross-correlation')
        plt.title('Cross-correlation: Arrival Rate vs PCIe RX')
        plt.legend()
        plt.tight_layout()
        plt.show()

if __name__ == "__main__":
    
    MODEL_LIST = [
        "Qwen_Qwen2.5-3B-Instruct-GPTQ-Int8",
        "Qwen_Qwen2.5-1.5B-Instruct",
        "RedHatAI_gemma-2-2b-it-quantized.w4a16",
        "RedHatAI_SmolLM-1.7B-Instruct-quantized.w8a16"
    ]

    MODEL_NAME=MODEL_LIST[2]
    REQUEST_RATE="-request_rate10.0"
    PATH="./data/artifacts_2/" + MODEL_NAME + "-openai-chat" + REQUEST_RATE + "/"
    PREFIX="Exclusive"

    gemma = vlllm_server(MODEL_NAME, PATH)
    gemma.analyze()


        