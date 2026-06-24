import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartSpecification } from "@/api/types";

const colors = ["#c94f2c", "#245c4d", "#7a6fc2", "#b78a1f", "#347a9a"];

function chartData(chart: ChartSpecification) {
  return chart.data.map((point) => {
    const values = Object.fromEntries(
      Object.entries(point.values).map(([key, value]) => [key, Number(value)]),
    );
    return { x: point.x, ...values };
  });
}

function Series({ chart }: { chart: ChartSpecification }) {
  if (chart.chart_type === "bar") {
    return chart.series.map((series, index) => (
      <Bar
        key={series.key}
        dataKey={series.key}
        fill={colors[index % colors.length]}
        name={series.label}
        radius={[3, 3, 0, 0]}
      />
    ));
  }
  if (chart.chart_type === "area") {
    return chart.series.map((series, index) => (
      <Area
        key={series.key}
        dataKey={series.key}
        fill={colors[index % colors.length]}
        fillOpacity={0.14}
        name={series.label}
        stroke={colors[index % colors.length]}
        strokeWidth={2}
        type="monotone"
      />
    ));
  }
  if (chart.chart_type === "scatter") {
    return chart.series.map((series, index) => (
      <Scatter
        key={series.key}
        dataKey={series.key}
        fill={colors[index % colors.length]}
        name={series.label}
      />
    ));
  }
  return chart.series.map((series, index) => (
    <Line
      key={series.key}
      dataKey={series.key}
      dot={false}
      name={series.label}
      stroke={colors[index % colors.length]}
      strokeWidth={2.25}
      type="monotone"
    />
  ));
}

export default function ResearchChart({ chart }: { chart: ChartSpecification }) {
  const data = chartData(chart);
  const common = (
    <>
      <CartesianGrid stroke="#d8d2c5" strokeDasharray="2 5" vertical={false} />
      <XAxis dataKey="x" minTickGap={28} tick={{ fill: "#65645f", fontSize: 11 }} />
      <YAxis tick={{ fill: "#65645f", fontSize: 11 }} width={52} />
      <Tooltip
        contentStyle={{
          background: "#fffdf8",
          border: "1px solid #cdc6b7",
          borderRadius: 2,
          fontFamily: "IBM Plex Sans Variable",
          fontSize: 12,
        }}
      />
      <Legend wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
      <Series chart={chart} />
    </>
  );

  return (
    <figure className="research-chart" aria-labelledby="chart-title">
      <figcaption>
        <span className="eyebrow">Validated chart</span>
        <h3 id="chart-title">{chart.title}</h3>
      </figcaption>
      <div className="chart-canvas" role="img" aria-label={`${chart.title}. ${chart.series.length} series.`}>
        <ResponsiveContainer width="100%" height="100%">
          {chart.chart_type === "bar" ? (
            <BarChart data={data}>{common}</BarChart>
          ) : chart.chart_type === "area" ? (
            <AreaChart data={data}>{common}</AreaChart>
          ) : chart.chart_type === "scatter" ? (
            <ScatterChart data={data}>{common}</ScatterChart>
          ) : (
            <LineChart data={data}>{common}</LineChart>
          )}
        </ResponsiveContainer>
      </div>
      <details className="chart-table-disclosure">
        <summary>View accessible data table</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{chart.x_label}</th>
                {chart.series.map((series) => (
                  <th key={series.key} scope="col">{series.label} ({series.unit})</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {chart.data.map((point) => (
                <tr key={point.x}>
                  <th scope="row">{point.x}</th>
                  {chart.series.map((series) => (
                    <td key={series.key}>{point.values[series.key]}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
