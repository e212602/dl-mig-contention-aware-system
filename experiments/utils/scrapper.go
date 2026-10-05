package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"text/tabwriter"
	"time"
)

// ---- Query definitions ----

// QueryDef pairs a short display name with the PromQL expression to run.
type QueryDef struct {
	Name  string // shown in table/JSON/CSV output
	Query string // PromQL expression sent to Prometheus
	Desc  string
}

// dcgmQueries are GPU profiling metrics queried by their bare metric name.
var dcgmQueries = []QueryDef{
	{"DCGM_FI_PROF_GR_ENGINE_ACTIVE", "DCGM_FI_PROF_GR_ENGINE_ACTIVE", "Ratio of time the graphics engine is active"},
	{"DCGM_FI_PROF_SM_ACTIVE", "DCGM_FI_PROF_SM_ACTIVE", "Ratio of cycles an SM has at least 1 warp assigned"},
	{"DCGM_FI_PROF_SM_OCCUPANCY", "DCGM_FI_PROF_SM_OCCUPANCY", "Ratio of number of warps resident on an SM"},
	{"DCGM_FI_PROF_PIPE_TENSOR_ACTIVE", "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE", "Ratio of cycles the tensor (HMMA) pipe is active"},
	{"DCGM_FI_PROF_DRAM_ACTIVE", "DCGM_FI_PROF_DRAM_ACTIVE", "Ratio of cycles the device memory interface is active"},
	{"DCGM_FI_PROF_PIPE_FP64_ACTIVE", "DCGM_FI_PROF_PIPE_FP64_ACTIVE", "Ratio of cycles the fp64 pipes are active"},
	{"DCGM_FI_PROF_PIPE_FP32_ACTIVE", "DCGM_FI_PROF_PIPE_FP32_ACTIVE", "Ratio of cycles the fp32 pipes are active"},
	{"DCGM_FI_PROF_PIPE_FP16_ACTIVE", "DCGM_FI_PROF_PIPE_FP16_ACTIVE", "Ratio of cycles the fp16 pipes are active"},
	{"DCGM_FI_PROF_PCIE_TX_BYTES", "DCGM_FI_PROF_PCIE_TX_BYTES", "Rate of data transmitted over PCIe bus (bytes/sec)"},
	{"DCGM_FI_PROF_PCIE_RX_BYTES", "DCGM_FI_PROF_PCIE_RX_BYTES", "Rate of data received over PCIe bus (bytes/sec)"},
}

// customQueries are non-DCGM PromQL expressions scraped alongside the DCGM metrics.
var customQueries = []QueryDef{
	{
		Name:  "pod_cpu_usage_cores",
		Query: `sum(rate(container_cpu_usage_seconds_total{namespace="default", pod=~".*", container!=""}[5m])) by (pod)`,
		Desc:  "CPU cores used per pod in the default namespace (5m rate)",
	},
	{
		Name:  "node_memory_used_percent",
		Query: `100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))`,
		Desc:  "Percentage of node memory in use",
	},
}

func allQueries() []QueryDef {
	qs := make([]QueryDef, 0, len(dcgmQueries)+len(customQueries))
	qs = append(qs, dcgmQueries...)
	return append(qs, customQueries...)
}

// maxResolutionPoints is Prometheus's cap on query_range: it rejects any series
// that would produce more than 11,000 points.
const maxResolutionPoints = 11000

// ---- Prometheus API response types ----

type prometheusResponse struct {
	Status string         `json:"status"`
	Data   prometheusData `json:"data"`
	Error  string         `json:"error,omitempty"`
}

type prometheusData struct {
	ResultType string         `json:"resultType"`
	Result     []matrixResult `json:"result"`
}

type matrixResult struct {
	Metric map[string]string `json:"metric"`
	Values [][]interface{}   `json:"values"` // [[timestamp, "value"], ...]
}

// ---- Domain types ----

type MetricSample struct {
	Timestamp time.Time
	Value     float64
	Labels    map[string]string
}

type MetricResult struct {
	Name    string
	Desc    string
	Samples []MetricSample
	Err     error
}

// ---- Prometheus client ----

type PrometheusClient struct {
	baseURL    string
	httpClient *http.Client
}

func NewPrometheusClient(baseURL string, timeout time.Duration) *PrometheusClient {
	return &PrometheusClient{
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: timeout},
	}
}

// QueryRange runs a PromQL expression over [start, end] with the given step.
func (c *PrometheusClient) QueryRange(ctx context.Context, query string, start, end time.Time, step time.Duration) ([]matrixResult, error) {
	apiURL := fmt.Sprintf("%s/api/v1/query_range", c.baseURL)

	params := url.Values{}
	params.Set("query", query)
	params.Set("start", strconv.FormatInt(start.Unix(), 10))
	params.Set("end", strconv.FormatInt(end.Unix(), 10))
	params.Set("step", formatStep(step))

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL+"?"+params.Encode(), nil)
	if err != nil {
		return nil, fmt.Errorf("building request: %w", err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading response body: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		// Prometheus returns a JSON body with the real reason; surface it.
		var errResp prometheusResponse
		if jsonErr := json.Unmarshal(body, &errResp); jsonErr == nil && errResp.Error != "" {
			return nil, fmt.Errorf("prometheus error (%s): %s", resp.Status, errResp.Error)
		}
		return nil, fmt.Errorf("unexpected HTTP status: %s - body: %s", resp.Status, string(body))
	}

	var promResp prometheusResponse
	if err := json.Unmarshal(body, &promResp); err != nil {
		return nil, fmt.Errorf("decoding response: %w", err)
	}
	if promResp.Status != "success" {
		return nil, fmt.Errorf("prometheus error: %s", promResp.Error)
	}

	return promResp.Data.Result, nil
}

// formatStep renders a step duration the way Prometheus expects, keeping
// sub-second precision instead of truncating to "0s".
func formatStep(step time.Duration) string {
	secs := step.Seconds()
	if secs == math.Trunc(secs) {
		return fmt.Sprintf("%.0fs", secs)
	}
	return fmt.Sprintf("%gs", secs)
}

// clampStep widens the step if (start, end, step) would exceed Prometheus's
// max-points-per-series limit. The bool reports whether an adjustment was made.
func clampStep(start, end time.Time, step time.Duration) (time.Duration, bool) {
	if step <= 0 {
		return step, false
	}
	duration := end.Sub(start)
	points := duration.Seconds()/step.Seconds() + 1
	if points <= maxResolutionPoints {
		return step, false
	}
	minStepSeconds := math.Ceil(duration.Seconds() / (maxResolutionPoints - 1))
	return time.Duration(minStepSeconds) * time.Second, true
}

// ---- Scraping ----

// parseSampleValue parses a Prometheus sample value, including "NaN", "+Inf"
// and "-Inf".
func parseSampleValue(s string) (float64, error) {
	return strconv.ParseFloat(s, 64)
}

// toSamples converts raw Prometheus matrix results into samples. Non-finite
// values (NaN/Inf, e.g. from division by zero) are skipped since they carry no
// usable data and cannot be encoded as JSON.
func toSamples(name string, raw []matrixResult) []MetricSample {
	var samples []MetricSample
	for _, r := range raw {
		for _, v := range r.Values {
			if len(v) != 2 {
				continue
			}
			ts, ok := v[0].(float64)
			if !ok {
				continue
			}
			valStr, ok := v[1].(string)
			if !ok {
				continue
			}
			val, err := parseSampleValue(valStr)
			if err != nil {
				log.Printf("warning: skipping unparsable sample for %s: %v", name, err)
				continue
			}
			if math.IsNaN(val) || math.IsInf(val, 0) {
				continue
			}
			samples = append(samples, MetricSample{
				Timestamp: time.Unix(int64(ts), 0).UTC(),
				Value:     val,
				Labels:    r.Metric,
			})
		}
	}
	return samples
}

// ScrapeMetrics runs all queries concurrently and returns results in query order.
func ScrapeMetrics(ctx context.Context, client *PrometheusClient, queries []QueryDef, start, end time.Time, step time.Duration) []MetricResult {
	results := make([]MetricResult, len(queries))
	done := make(chan struct{}, len(queries))

	for i, q := range queries {
		go func(idx int, q QueryDef) {
			defer func() { done <- struct{}{} }()

			raw, err := client.QueryRange(ctx, q.Query, start, end, step)
			res := MetricResult{Name: q.Name, Desc: q.Desc, Err: err}
			if err == nil {
				res.Samples = toSamples(q.Name, raw)
			}
			results[idx] = res // each goroutine writes a distinct index
		}(i, q)
	}

	for range queries {
		<-done
	}
	return results
}

// ---- Output helpers ----

func labelsKey(labels map[string]string) string {
	b, _ := json.Marshal(labels)
	return string(b)
}

func printResults(results []MetricResult) {
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)

	for _, r := range results {
		fmt.Fprintf(w, "\n=== %s ===\n", r.Name)
		fmt.Fprintf(w, "    %s\n", r.Desc)

		if r.Err != nil {
			fmt.Fprintf(w, "    ERROR: %v\n", r.Err)
			continue
		}
		if len(r.Samples) == 0 {
			fmt.Fprintln(w, "    No data in the requested interval.")
			continue
		}

		// Group samples by label set for readability.
		byLabel := map[string][]MetricSample{}
		var labelOrder []string
		for _, s := range r.Samples {
			key := labelsKey(s.Labels)
			if _, exists := byLabel[key]; !exists {
				labelOrder = append(labelOrder, key)
			}
			byLabel[key] = append(byLabel[key], s)
		}

		for _, key := range labelOrder {
			samples := byLabel[key]
			fmt.Fprintf(w, "\n    Labels: %v\n", samples[0].Labels)
			fmt.Fprintln(w, "    Timestamp\t\t\tValue")
			fmt.Fprintln(w, "    ---------\t\t\t-----")
			for _, s := range samples {
				fmt.Fprintf(w, "    %s\t\t%.6f\n", s.Timestamp.Format(time.RFC3339), s.Value)
			}
		}
	}
	w.Flush()
}

func printJSON(results []MetricResult) error {
	type jsonSample struct {
		Timestamp string            `json:"timestamp"`
		Value     float64           `json:"value"`
		Labels    map[string]string `json:"labels"`
	}
	type jsonResult struct {
		Metric      string       `json:"metric"`
		Description string       `json:"description"`
		Error       string       `json:"error,omitempty"`
		Samples     []jsonSample `json:"samples"`
	}

	out := make([]jsonResult, 0, len(results))
	for _, r := range results {
		jr := jsonResult{
			Metric:      r.Name,
			Description: r.Desc,
			Samples:     []jsonSample{},
		}
		if r.Err != nil {
			jr.Error = r.Err.Error()
		}
		for _, s := range r.Samples {
			jr.Samples = append(jr.Samples, jsonSample{
				Timestamp: s.Timestamp.Format(time.RFC3339),
				Value:     s.Value,
				Labels:    s.Labels,
			})
		}
		out = append(out, jr)
	}

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(out)
}

// writeCSV writes one row per sample: metric, description, timestamp, value,
// labels (as a JSON object) and error. Metrics that errored or returned no
// samples still get a single row so nothing silently disappears.
func writeCSV(results []MetricResult, path string) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("creating CSV file: %w", err)
	}
	defer f.Close()

	w := csv.NewWriter(f)

	if err := w.Write([]string{"metric", "description", "timestamp", "value", "labels", "error"}); err != nil {
		return fmt.Errorf("writing CSV header: %w", err)
	}

	for _, r := range results {
		switch {
		case r.Err != nil:
			if err := w.Write([]string{r.Name, r.Desc, "", "", "", r.Err.Error()}); err != nil {
				return fmt.Errorf("writing CSV row for %s: %w", r.Name, err)
			}
		case len(r.Samples) == 0:
			if err := w.Write([]string{r.Name, r.Desc, "", "", "", "no data in requested interval"}); err != nil {
				return fmt.Errorf("writing CSV row for %s: %w", r.Name, err)
			}
		default:
			for _, s := range r.Samples {
				row := []string{
					r.Name,
					r.Desc,
					s.Timestamp.Format(time.RFC3339),
					fmt.Sprintf("%.6f", s.Value),
					labelsKey(s.Labels),
					"",
				}
				if err := w.Write(row); err != nil {
					return fmt.Errorf("writing CSV row for %s: %w", r.Name, err)
				}
			}
		}
	}

	w.Flush()
	if err := w.Error(); err != nil {
		return fmt.Errorf("flushing CSV writer: %w", err)
	}
	return nil
}

// ---- Time parsing ----

// parseTime accepts RFC3339 strings or Unix timestamps.
func parseTime(s string) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t.UTC(), nil
	}
	if unix, err := strconv.ParseInt(s, 10, 64); err == nil {
		return time.Unix(unix, 0).UTC(), nil
	}
	return time.Time{}, fmt.Errorf("cannot parse %q as RFC3339 or Unix timestamp", s)
}

// ---- Main ----

func main() {
	var (
		promAddr  = flag.String("addr", "http://localhost:9090", "Prometheus base URL (e.g. http://localhost:9090)")
		startStr  = flag.String("start", "", "Start time (RFC3339 or Unix timestamp). Defaults to 1 hour ago.")
		endStr    = flag.String("end", "", "End time   (RFC3339 or Unix timestamp). Defaults to now.")
		stepStr   = flag.String("step", "60s", "Query resolution step (e.g. 15s, 1m, 5m)")
		timeout   = flag.Duration("timeout", 30*time.Second, "HTTP request timeout")
		outputFmt = flag.String("output", "table", "Output format: table | json")
		csvFile   = flag.String("csv-file", "", "If set, also write results to this CSV file path")
	)
	flag.Parse()

	step, err := time.ParseDuration(*stepStr)
	if err != nil {
		log.Fatalf("invalid --step %q: %v", *stepStr, err)
	}
	if step <= 0 {
		log.Fatalf("--step must be positive, got %s", step)
	}

	now := time.Now().UTC()
	start, end := now.Add(-1*time.Hour), now

	if *startStr != "" {
		if start, err = parseTime(*startStr); err != nil {
			log.Fatalf("invalid --start %q: %v", *startStr, err)
		}
	}
	if *endStr != "" {
		if end, err = parseTime(*endStr); err != nil {
			log.Fatalf("invalid --end %q: %v", *endStr, err)
		}
	}
	if !end.After(start) {
		log.Fatalf("--end (%s) must be after --start (%s)", end.Format(time.RFC3339), start.Format(time.RFC3339))
	}

	// Auto-widen the step rather than failing every query with a 400.
	if adjusted, changed := clampStep(start, end, step); changed {
		log.Printf("warning: --step %s over a %s window would exceed Prometheus's "+
			"%d-point-per-series limit; using --step %s instead",
			step, end.Sub(start), maxResolutionPoints, adjusted)
		step = adjusted
	}

	queries := allQueries()

	fmt.Printf("Prometheus : %s\n", *promAddr)
	fmt.Printf("Start      : %s\n", start.Format(time.RFC3339))
	fmt.Printf("End        : %s\n", end.Format(time.RFC3339))
	fmt.Printf("Step       : %s\n", step)
	fmt.Printf("Queries    : %d (%d DCGM + %d custom)\n\n", len(queries), len(dcgmQueries), len(customQueries))

	client := NewPrometheusClient(*promAddr, *timeout)
	results := ScrapeMetrics(context.Background(), client, queries, start, end, step)

	switch *outputFmt {
	case "json":
		if err := printJSON(results); err != nil {
			log.Fatalf("writing JSON: %v", err)
		}
	default:
		printResults(results)
	}

	if *csvFile != "" {
		if err := writeCSV(results, *csvFile); err != nil {
			log.Fatalf("writing CSV: %v", err)
		}
		fmt.Printf("\nCSV written to %s\n", *csvFile)
	}
}
