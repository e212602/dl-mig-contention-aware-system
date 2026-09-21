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
	"text/tabwriter"
	"time"
)

// DCGM metrics to scrape
var dcgmMetrics = []string{
	"DCGM_FI_PROF_GR_ENGINE_ACTIVE",
	"DCGM_FI_PROF_SM_ACTIVE",
	"DCGM_FI_PROF_SM_OCCUPANCY",
	"DCGM_FI_PROF_PIPE_TENSOR_ACTIVE",
	"DCGM_FI_PROF_DRAM_ACTIVE",
	"DCGM_FI_PROF_PIPE_FP64_ACTIVE",
	"DCGM_FI_PROF_PIPE_FP32_ACTIVE",
	"DCGM_FI_PROF_PIPE_FP16_ACTIVE",
	"DCGM_FI_PROF_PCIE_TX_BYTES",
	"DCGM_FI_PROF_PCIE_RX_BYTES",
}

var metricDescriptions = map[string]string{
	"DCGM_FI_PROF_GR_ENGINE_ACTIVE":   "Ratio of time the graphics engine is active",
	"DCGM_FI_PROF_SM_ACTIVE":          "Ratio of cycles an SM has at least 1 warp assigned",
	"DCGM_FI_PROF_SM_OCCUPANCY":       "Ratio of number of warps resident on an SM",
	"DCGM_FI_PROF_PIPE_TENSOR_ACTIVE": "Ratio of cycles the tensor (HMMA) pipe is active",
	"DCGM_FI_PROF_DRAM_ACTIVE":        "Ratio of cycles the device memory interface is active",
	"DCGM_FI_PROF_PIPE_FP64_ACTIVE":   "Ratio of cycles the fp64 pipes are active",
	"DCGM_FI_PROF_PIPE_FP32_ACTIVE":   "Ratio of cycles the fp32 pipes are active",
	"DCGM_FI_PROF_PIPE_FP16_ACTIVE":   "Ratio of cycles the fp16 pipes are active",
	"DCGM_FI_PROF_PCIE_TX_BYTES":      "Rate of data transmitted over PCIe bus (bytes/sec)",
	"DCGM_FI_PROF_PCIE_RX_BYTES":      "Rate of data received over PCIe bus (bytes/sec)",
}

// maxResolutionPoints mirrors Prometheus's default query.max-samples-per-query
// style cap on query_range: it rejects any series that would produce more than
// 11,000 points ("exceeded maximum resolution of 11,000 points per timeseries").
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
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

// QueryRange queries a metric over [start, end] with the given step.
func (c *PrometheusClient) QueryRange(ctx context.Context, metric string, start, end time.Time, step time.Duration) ([]matrixResult, error) {
	apiURL := fmt.Sprintf("%s/api/v1/query_range", c.baseURL)

	params := url.Values{}
	params.Set("query", metric)
	params.Set("start", fmt.Sprintf("%d", start.Unix()))
	params.Set("end", fmt.Sprintf("%d", end.Unix()))
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

	body, readErr := io.ReadAll(resp.Body)
	if readErr != nil {
		return nil, fmt.Errorf("reading response body: %w", readErr)
	}

	if resp.StatusCode != http.StatusOK {
		// Prometheus returns a JSON body with the real reason
		// (e.g. "exceeded maximum resolution of 11,000 points per timeseries").
		// Surface that instead of just the bare status code.
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

// formatStep renders a step duration the way Prometheus expects. Using whole
// seconds via "%.0fs" silently truncates sub-second steps (e.g. 500ms -> "0s",
// which Prometheus rejects), so fall back to a fractional-second representation
// when the step doesn't land on a whole second.
func formatStep(step time.Duration) string {
	secs := step.Seconds()
	if secs == math.Trunc(secs) {
		return fmt.Sprintf("%.0fs", secs)
	}
	return fmt.Sprintf("%gs", secs)
}

// clampStep ensures the (start, end, step) combination won't exceed Prometheus's
// max-points-per-series limit for query_range. If it would, it returns an
// adjusted step that fits within the limit, along with a bool indicating
// whether an adjustment was made.
func clampStep(start, end time.Time, step time.Duration) (time.Duration, bool) {
	duration := end.Sub(start)
	if step <= 0 {
		return step, false
	}
	points := duration.Seconds()/step.Seconds() + 1
	if points <= maxResolutionPoints {
		return step, false
	}
	minStepSeconds := math.Ceil(duration.Seconds() / (maxResolutionPoints - 1))
	return time.Duration(minStepSeconds) * time.Second, true
}

// ScrapeMetrics fetches all DCGM metrics concurrently for the given window.
func ScrapeMetrics(ctx context.Context, client *PrometheusClient, start, end time.Time, step time.Duration) []MetricResult {
	results := make([]MetricResult, len(dcgmMetrics))
	ch := make(chan struct {
		idx int
		res MetricResult
	}, len(dcgmMetrics))

	for i, metric := range dcgmMetrics {
		go func(idx int, name string) {
			raw, err := client.QueryRange(ctx, name, start, end, step)
			res := MetricResult{
				Name: name,
				Desc: metricDescriptions[name],
				Err:  err,
			}
			if err == nil {
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
						val, parseErr := parseSampleValue(valStr)
						if parseErr != nil {
							log.Printf("warning: skipping unparsable sample for %s: %v", name, parseErr)
							continue
						}
						res.Samples = append(res.Samples, MetricSample{
							Timestamp: time.Unix(int64(ts), 0).UTC(),
							Value:     val,
							Labels:    r.Metric,
						})
					}
				}
			}
			ch <- struct {
				idx int
				res MetricResult
			}{idx, res}
		}(i, metric)
	}

	for range dcgmMetrics {
		got := <-ch
		results[got.idx] = got.res
	}
	return results
}

// parseSampleValue parses a Prometheus sample value string, which may be a
// normal float, or the "NaN"/"+Inf"/"-Inf" markers Prometheus uses for stale
// or undefined samples.
func parseSampleValue(s string) (float64, error) {
	var val float64
	n, err := fmt.Sscanf(s, "%f", &val)
	if err != nil || n != 1 {
		return 0, fmt.Errorf("cannot parse sample value %q", s)
	}
	return val, nil
}

// ---- Output helpers ----

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

		// Group samples by label set for readability
		byLabel := map[string][]MetricSample{}
		labelOrder := []string{}
		for _, s := range r.Samples {
			key := labelsKey(s.Labels)
			if _, exists := byLabel[key]; !exists {
				labelOrder = append(labelOrder, key)
			}
			byLabel[key] = append(byLabel[key], s)
		}

		for _, key := range labelOrder {
			samples := byLabel[key]
			if len(samples) > 0 {
				fmt.Fprintf(w, "\n    Labels: %v\n", samples[0].Labels)
				fmt.Fprintln(w, "    Timestamp\t\t\tValue")
				fmt.Fprintln(w, "    ---------\t\t\t-----")
				for _, s := range samples {
					fmt.Fprintf(w, "    %s\t\t%.6f\n", s.Timestamp.Format(time.RFC3339), s.Value)
				}
			}
		}
	}
	w.Flush()
}

func labelsKey(labels map[string]string) string {
	b, _ := json.Marshal(labels)
	return string(b)
}

func printJSON(results []MetricResult) {
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
	enc.Encode(out)
}

// writeCSV writes the scraped results to a CSV file at path. Each row is one
// sample: metric name, description, timestamp, value, and the labels for
// that series (serialized as a JSON object so multi-label sets stay in one
// column). Metrics that errored or returned no samples still get a single
// row noting that, so nothing silently disappears from the output.
func writeCSV(results []MetricResult, path string) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("creating CSV file: %w", err)
	}
	defer f.Close()

	w := csv.NewWriter(f)
	defer w.Flush()

	header := []string{"metric", "description", "timestamp", "value", "labels", "error"}
	if err := w.Write(header); err != nil {
		return fmt.Errorf("writing CSV header: %w", err)
	}

	for _, r := range results {
		if r.Err != nil {
			if err := w.Write([]string{r.Name, r.Desc, "", "", "", r.Err.Error()}); err != nil {
				return fmt.Errorf("writing CSV row for %s: %w", r.Name, err)
			}
			continue
		}
		if len(r.Samples) == 0 {
			if err := w.Write([]string{r.Name, r.Desc, "", "", "", "no data in requested interval"}); err != nil {
				return fmt.Errorf("writing CSV row for %s: %w", r.Name, err)
			}
			continue
		}
		for _, s := range r.Samples {
			labelBytes, _ := json.Marshal(s.Labels)
			row := []string{
				r.Name,
				r.Desc,
				s.Timestamp.Format(time.RFC3339),
				fmt.Sprintf("%.6f", s.Value),
				string(labelBytes),
				"",
			}
			if err := w.Write(row); err != nil {
				return fmt.Errorf("writing CSV row for %s: %w", r.Name, err)
			}
		}
	}

	if err := w.Error(); err != nil {
		return fmt.Errorf("flushing CSV writer: %w", err)
	}
	return nil
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

	// Parse step
	step, err := time.ParseDuration(*stepStr)
	if err != nil {
		log.Fatalf("invalid --step %q: %v", *stepStr, err)
	}

	// Parse start
	now := time.Now().UTC()
	var start, end time.Time

	if *startStr == "" {
		start = now.Add(-1 * time.Hour)
	} else {
		start, err = parseTime(*startStr)
		if err != nil {
			log.Fatalf("invalid --start %q: %v", *startStr, err)
		}
	}

	// Parse end
	if *endStr == "" {
		end = now
	} else {
		end, err = parseTime(*endStr)
		if err != nil {
			log.Fatalf("invalid --end %q: %v", *endStr, err)
		}
	}

	if !end.After(start) {
		log.Fatalf("--end (%s) must be after --start (%s)", end.Format(time.RFC3339), start.Format(time.RFC3339))
	}

	// Prometheus's query_range endpoint rejects any query that would return
	// more than 11,000 points for a single series. Rather than failing with a
	// 400 for every metric, auto-widen the step to fit and warn the user.
	if adjusted, changed := clampStep(start, end, step); changed {
		log.Printf("warning: --step %s over a %s window would exceed Prometheus's "+
			"%d-point-per-series limit; using --step %s instead",
			step, end.Sub(start), maxResolutionPoints, adjusted)
		step = adjusted
	}

	fmt.Printf("Prometheus : %s\n", *promAddr)
	fmt.Printf("Start      : %s\n", start.Format(time.RFC3339))
	fmt.Printf("End        : %s\n", end.Format(time.RFC3339))
	fmt.Printf("Step       : %s\n", step)
	fmt.Printf("Metrics    : %d DCGM metrics\n\n", len(dcgmMetrics))

	client := NewPrometheusClient(*promAddr, *timeout)
	ctx := context.Background()

	results := ScrapeMetrics(ctx, client, start, end, step)

	switch *outputFmt {
	case "json":
		printJSON(results)
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

// parseTime accepts RFC3339 strings or Unix timestamps (as strings).
func parseTime(s string) (time.Time, error) {
	// Try RFC3339 first
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t.UTC(), nil
	}
	// Try Unix timestamp
	var unix int64
	if _, err := fmt.Sscanf(s, "%d", &unix); err == nil {
		return time.Unix(unix, 0).UTC(), nil
	}
	return time.Time{}, fmt.Errorf("cannot parse %q as RFC3339 or Unix timestamp", s)
}
