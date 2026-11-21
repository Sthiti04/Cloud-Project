import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';

export const options = {
  scenarios: {
    sustained: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.LOAD_RATE || 90),
      timeUnit: '1s',
      duration: __ENV.LOAD_DURATION || '10m',
      preAllocatedVUs: 30,
      maxVUs: 150,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
    checks: ['rate>0.95'],
    dropped_iterations: ['count==0'],
  },
};

export default function () {
  const sequence = exec.scenario.iterationInTest;
  const device = (sequence % 3) + 1;
  const reading = {
    event_id: `load-${__VU}-${__ITER}-${Date.now()}`,
    device_id: `device-${device}`,
    patient_id: `patient-${device}`,
    heart_rate: sequence % 100 === 0 ? 145 : 72,
    observed_at: Date.now(),
  };
  const response = http.post(`${__ENV.BASE_URL}/readings`, JSON.stringify(reading), {
    headers: { 'Content-Type': 'application/json', 'X-API-Key': __ENV.API_KEY },
    timeout: '10s',
  });
  check(response, { 'reading accepted': (r) => r.status === 202 });
}
