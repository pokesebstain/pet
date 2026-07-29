import { http } from '@/api/client';
export async function listPage(path, params = {}) {
    const { data } = await http.get(path, { params });
    return data;
}
export async function getOne(path) {
    const { data } = await http.get(path);
    return data;
}
export async function createOne(path, payload) {
    const { data } = await http.post(path, payload);
    return data;
}
export async function updateOne(path, payload) {
    const { data } = await http.put(path, payload);
    return data;
}
export async function deleteOne(path) {
    await http.delete(path);
}
//# sourceMappingURL=http.js.map